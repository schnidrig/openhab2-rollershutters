
# Copyright (c) 2017 by Christian Schnidrig.

# jython imports
import logging
import uuid
import math
import sys
import traceback
import time
from threading import Thread

# java imports
from org.eclipse.smarthome.core.scheduler import CronExpression
from java.util import Date, Locale
from java.text import DateFormat
from org.yaml.snakeyaml import Yaml
import profile
from org.eclipse.smarthome.core.service import AbstractWatchService
from java.nio.file import FileSystems,WatchService,Path,StandardWatchEventKinds
from threading import Thread

# openhab2 jsr223 stuff
scriptExtension.importPreset("RuleSupport")
scriptExtension.importPreset("RuleSimple")

#######################################################
#######################################################
#######################################################
# constants

module_name = "shutters"
module_prefix = module_name + "_"

# item name prefix
prefix_auto = "state_auto_"
prefix_sunlit = "state_sunlit_"

# auto state names
autoStateSun = "SUN"
autoStateDown = "DOWN"
autoStateUp = "UP"
autoStateManual = "MANUAL"

# sunlit state names
sunlitStateUnknown = "Unknown"
sunlitStateTrue = "True"
sunlitStateFalse = "False"

# location of script
automationDir = '/etc/openhab2/automation/jsr223'

shuttersFileName = 'shutters.yml'
scheduleFileName = 'shutter_schedule.yml'
shuttersFile = automationDir + '/' + shuttersFileName
scheduleFile = automationDir + '/' + scheduleFileName

#######################################################
# some globals
config = None
calendar = None

# defaut logger
logger = logging.getLogger(module_name)

# globalRules
globalRules = None

#######################################################
#######################################################
#######################################################
# config
class Config():
    def __init__(self):
        self.logger = logging.getLogger(module_name + ":Config")
        self.shutterConfig = Yaml().load(open(shuttersFile))
        self.scheduleConfig = Yaml().load(open(scheduleFile))
        self.logger.info("Config loaded")

    def getShutters(self):
        return self.shutterConfig['sun_exposure']

    def getSunExposure(self):
        return self.shutterConfig['sun_exposure']

    def getItems(self):
        return self.shutterConfig['items']

    def getCalendar(self):
        return self.scheduleConfig['calendar']

    def getDailySchedules(self):
        return self.scheduleConfig['daily_schedules']

    def getRules(self):
        return self.scheduleConfig['rules']

#######################################################
def initStateItems(force=False, states=None):
    logger = logging.getLogger(module_name + ":initStateItems")
    if states == None:
        states = {prefix_auto: autoStateDown, prefix_sunlit: sunlitStateFalse}
    for item_name in config.getShutters():
        #logger.info(ir.get(item_name))
        for prefix in states:
            item = ir.get(prefix + item_name)
            logger.debug(item)
            if str(item.getState()) == "NULL" or force:
                events.postUpdate(item.getName(), states[prefix])

#######################################################
def normalize_name(name, prefix=None):
    if prefix == None:
        prefix = module_prefix
    if name == None:
        name = prefix + uuid.uuid1().hex
    else:
        name = name.replace("#", "_")
        name = name.replace(":", "_")
        name = prefix + name
    return name

#######################################################
#######################################################
#######################################################
# Triggers

class CronTrigger(Trigger):
    def __init__(self, cronExpression, triggerName=None):
        triggerName = normalize_name(triggerName)
        Trigger.__init__(self, triggerName, "timer.GenericCronTrigger", Configuration({
                "cronExpression": cronExpression
                }))

class ChannelEventCondition(Condition):
    def __init__(self, triggerName, event, conditionName=None):
        conditionName = normalize_name(conditionName)
        triggerName = normalize_name(triggerName)
        logger.info("Condition: " + conditionName + "; Trigger: " + triggerName)
        Condition.__init__(self, conditionName, "core.GenericEventCondition", Configuration({
            "payload": event
        }), {
            "event": triggerName+".event"
            })

class ChannelEventTrigger(Trigger):
    def __init__(self, channelUID, triggerName=None):
        triggerName = normalize_name(triggerName)
        logger.info("Trigger: " + triggerName + "; channel: " + channelUID)
        Trigger.__init__(self, triggerName, "core.GenericEventTrigger", Configuration({
                "eventTopic": "smarthome/channels/*/triggered",
                "eventSource": channelUID,
                "eventTypes": "ChannelTriggeredEvent"
                }))

class StartupTrigger(Trigger):
    def __init__(self, triggerName=None):
        triggerName = normalize_name(triggerName)
        Trigger.__init__(self, triggerName, STARTUP_MODULE_ID, Configuration())

class ItemStateChangeTrigger(Trigger):
    def __init__(self, itemName, state=None, triggerName=None):
        triggerName = normalize_name(triggerName)
        config = { "itemName": itemName }
        if state is not None:
            config["state"] = state
        Trigger.__init__(self, triggerName, "core.ItemStateChangeTrigger", Configuration(config))


#######################################################
#######################################################
#######################################################
# Shutters


#######################################################
class Horizon():
    def __init__(self, orientation, config):
        self.logger = logging.getLogger(module_name + ":Horizon")
        self.elevation = config['elevation']
    def getElevationAtAzimuth(self, azimuth):
        return self.elevation


#######################################################
class HLine():
    def __init__(self, orientation, config):
        self.logger = logging.getLogger(module_name + ":HLine")
        self.orientation = orientation
        self.profileAngle = self._calculateProfileAngle(config['elevation'], config['azimuth'])
        self.logger.debug("profileAngle: " + str(self.profileAngle) + "/*")

    def getElevationAtAzimuth(self, azimuth):
        return self._getElevationAtAzimuth(azimuth, self.profileAngle)

    def _calculateProfileAngle(self, elevation, azimuth):
        return math.degrees(
            math.atan(
                math.tan( math.radians( elevation ) )
                /
                math.sin( math.radians( azimuth - self.orientation + 90 ))
            )
        )

    def _getElevationAtAzimuth(self, azimuth, profileAngle):
        self.logger.debug( str(azimuth) + ";" + str(profileAngle) )
        return math.degrees(
            math.atan(
                math.sin( math.radians(azimuth-self.orientation+90) )
                *
                math.tan( math.radians(profileAngle) )
            )
        )

#######################################################
class Line(HLine):
    def __init__(self, orientation, config):
        self.logger = logging.getLogger(module_name + ":Line")
        self.orientation = orientation
        self.azimuth1 = config[0]['azimuth']
        self.azimuth2 = config[1]['azimuth']
        self.profileAngle1 = self._calculateProfileAngle(config[0]['elevation'], self.azimuth1)
        self.profileAngle2 = self._calculateProfileAngle(config[1]['elevation'], self.azimuth2)
        self.inclination = 1.0 * (self.profileAngle2 - self.profileAngle1) / (self.azimuth2 - self.azimuth1)
        self.logger.debug(str(self.profileAngle1) + "/" + str(self.azimuth1) + "; " + str(self.profileAngle2) + "/" + str(self.azimuth2) + "; " + str(self.inclination))

    def getElevationAtAzimuth(self, azimuth):
        return self._getElevationAtAzimuth(azimuth, max(min((azimuth - self.azimuth1) * self.inclination + self.profileAngle1, 90),0))


#######################################################
class SunExposure():
    def __init__(self, config):
        self.logger = logging.getLogger(module_name + ":SunExposure")
        self.config = config
        self.openings = {}
        self.orientation = config['orientation']
        self._parseSunOpenings()

    def _parseSunOpenings(self):
        for opening_config in self.config['sun_openings']:
            opening = {}
            for position in ['above', 'below' ]:
                opening[position] = None
                if opening_config.get(position) != None:
                    if len(opening_config[position]) == 1:
                        if (opening_config[position][0].get('azimuth') == None ):
                            opening[position] = Horizon(self.orientation, opening_config[position][0])
                        else:
                            opening[position] = HLine(self.orientation, opening_config[position][0])
                    else:
                        opening[position] = Line(self.orientation, opening_config[position])
            self.openings[opening_config['azimuth']] = opening

    def isSunlit(self, azimuth, elevation):
        self.logger.debug(str(azimuth) + "-" + str(elevation))
        sections = sorted(list(self.openings))
        self.logger.debug(self.config)
        self.logger.debug(sections)
        section = None
        for i in sections:
            self.logger.debug("i: " + str(i) + "; " + str(azimuth))
            if float(i) > float(str(azimuth)):
                break
            else:
                section = i
        self.logger.debug(section)
        if section == sections[len(sections)-1]:
            return False
        if section == None:
            return False
        sunlit = True
        if self.openings[section].get('above') != None:
            e1 = self.openings[section]['above'].getElevationAtAzimuth(azimuth)
            self.logger.debug ("above: " + str(elevation) + ">" + str(e1) )
            sunlit = float(str(elevation)) > e1
        if self.openings[section].get('below') != None:
            e2 = self.openings[section]['below'].getElevationAtAzimuth(azimuth)
            self.logger.debug ("below: " + str(elevation) + "<" + str(e2) )
            sunlit = sunlit and (float(str(elevation)) < e2)
        return sunlit



#######################################################
# tests
class ShutterTest():
    def __init__(self):
        self.logger = logging.getLogger(module_name + ":ShutterTest")

    def horizonTest(self):
        self.logger.info("horizonTest")
        horizon = Horizon(240, Yaml().load("{ elevation: 53 }"))
        assert horizon.getElevationAtAzimuth(60) == 53
        assert horizon.getElevationAtAzimuth(200) == 53

    def hLineTest(self):
        self.logger.info("hLineTest")
        hline = HLine(240, Yaml().load("{ azimuth: 240, elevation: 60 }"))
        t1 = round(hline.getElevationAtAzimuth(240))
        self.logger.debug(t1)
        assert t1 == 60

        t2 = hline.getElevationAtAzimuth(200)
        self.logger.debug(t2)
        assert t2 < 55 and t2 > 50

        hline2 = HLine(240, Yaml().load("{ azimuth: 200, elevation: 53 }"))
        t3 = hline2.getElevationAtAzimuth(240)
        assert round(t3) == 60
        t4 = hline2.getElevationAtAzimuth(60)
        assert t4 < 0

    def lineTest(self):
        self.logger.info("lineTest")
        line = Line(240, Yaml().load("""
             - { azimuth: 224, elevation: 57 }
             - { azimuth: 227, elevation: 59 }
             """))

        t1 = line.getElevationAtAzimuth(240)
        self.logger.debug(t1)
        assert round(t1) == 67
        assert round(line.getElevationAtAzimuth(224)) == 57
        assert round(line.getElevationAtAzimuth(227)) == 59
        t2 = round(line.getElevationAtAzimuth(280))
        self.logger.debug(t2)
        assert t2 > 64 and t2 < 90
        assert round(line.getElevationAtAzimuth(290)) == 90
        assert round(line.getElevationAtAzimuth(160)) > 0
        assert round(line.getElevationAtAzimuth(60)) == 0

    def sunExposureTest(self):
        self.logger.info("sunExposureTest")
        se = SunExposure(Yaml().load("""
            orientation: 240
            sun_openings:
              - azimuth: 160
                below:
                  - { azimuth: 240, elevation: 60 }
                above:
                  - { elevation: 5 }
              - azimuth: 240
                below:
                  - { azimuth: 240, elevation: 60 }
                above:
                  - { elevation: 3 }
              - azimuth: 330
            """))
        assert se.isSunlit(159, 9) == False

        assert se.isSunlit(161, 15) == True
        assert se.isSunlit(161, 6) == True
        assert se.isSunlit(161, 4) == False

        assert se.isSunlit(241, 58) == True
        assert se.isSunlit(241, 62) == False
        assert se.isSunlit(241, 4) == True
        assert se.isSunlit(325, 4) == True

        assert se.isSunlit(331, 4) == False

        se2 = SunExposure(Yaml().load("""
            orientation: 240
            sun_openings:
              - azimuth: 160
              - azimuth: 330
            """))
        assert se2.isSunlit(200, 9) == True

    def run(self):
        self.logger.info("TEST start")
        try:
            self.horizonTest()
            self.hLineTest()
            self.lineTest()
            self.sunExposureTest()
        except Exception as e:
            self.logger.error(traceback.format_exc())

        self.logger.info("TEST end")

#######################################################
#######################################################
#######################################################
# Rules


class ShutterBaseRule(SimpleRule):
    def __init__(self, shutterAutomationItem, testing=False):
        self.testing = testing
        self.shutterAutomationItem = ir.get(shutterAutomationItem)

    def sendCommand(self, shutterName, state, auto):
        if not auto:
            self.logger.info("Auto(OFF): Not sending command: " + shutterName + "=" + state)
        else:
            self.logger.info("Auto(ON): sending command: " + shutterName + "=" + state)
            if self.testing:
                events.sendCommand(shutterName, state if state != "STOP" else "50")
            else:
                events.sendCommand(shutterName, state)

#######################################################
# Sun Exposure Rule

class SunExposureRule(ShutterBaseRule):
    def __init__(self, exposure, azimuthItem, elevationItem, isSunnyItem, shutterAutomationItem, testing=False):
        #super(ShutterBaseRule, self).__init__(shutterAutomationItem, testing)
        ShutterBaseRule.__init__(self, shutterAutomationItem, testing)
        self.logger = logging.getLogger(module_name + ":SunExposureRule")
        self.exposure = exposure
        self.elevationItem = ir.get(elevationItem)
        self.isSunnyItem = ir.get(isSunnyItem)
        self.setTriggers([ItemStateChangeTrigger(azimuthItem)])

    def _execute(self, azimuth, elevation, auto):
        self.logger.info("azimuth: " + str(azimuth) + "; elevation: " + str(elevation))

        for shutterName in self.exposure:
            shutterAutoState = ir.get(prefix_auto + shutterName).getState().toString()
            isSunny = self.isSunnyItem.getState().toString() == "ON"
            if shutterAutoState == autoStateSun:
                sunlitState = ir.get(prefix_sunlit + shutterName).getState().toString()
                isSunlit = self.exposure[shutterName].isSunlit(azimuth, elevation)
                self.logger.info(shutterName + " isSunlit: " + str(isSunlit))
                if isSunlit:
                    if isSunny:
                        if sunlitState == sunlitStateFalse:
                            self.sendCommand(shutterName, "STOP", auto)
                            events.postUpdate(prefix_sunlit + shutterName, sunlitStateTrue)
                        else:
                            if sunlitState == sunlitStateUnknown:
                                events.postUpdate(prefix_sunlit + shutterName, sunlitStateTrue)

                else:
                    if sunlitState == sunlitStateTrue:
                        self.sendCommand(shutterName, "UP", auto)
                        events.postUpdate(prefix_sunlit + shutterName, sunlitStateFalse)
                    else:
                        if sunlitState == sunlitStateUnknown:
                            events.postUpdate(prefix_sunlit + shutterName, sunlitStateTrue)
            else:
                self.logger.info(shutterName + " is: " + str(shutterAutoState))

    def execute(self, module, input):
        self.logger.debug("Executing Exposure Rule: ")
        azimuth = float(str(input['newState']))
        elevation = float(self.elevationItem.getState().toString())
        auto = self.shutterAutomationItem.getState().toString() == "ON"
        self._execute(azimuth, elevation, auto)


def setupSunExposureRule(exposureConfig, items):
    exposure = {}
    for shutter in exposureConfig:
        exposure[shutter] = SunExposure(exposureConfig[shutter])
    globalRules.append(SunExposureRule(exposure, items['azimuth'], items['elevation'], items['weather_sunny'], items['shutter_automation']))


#######################################################
# Shutter Rule

class ShutterScheduleRule(ShutterBaseRule):
    def __init__(self, action, items, ruleName, shutterAutomationItem, testing=False):
        ShutterBaseRule.__init__(self, shutterAutomationItem, testing)
        self.logger = logging.getLogger(module_name + ":ShutterScheduleRule")
        self.action = action
        self.items = items
        self.triggerList = []
        self.conditionList = []
        self.ruleName = normalize_name(ruleName, "")
        self.prefixedRuleName = normalize_name(self.ruleName)

    def addCronTrigger(self, schedule):
        name = self.ruleName + "-cron:" + str(schedule).replace("*", "s").replace("?", "q").replace(" ", "l").replace("/", "x")
        triggerName = name + "_trigger"
        self.triggerList.append(CronTrigger(schedule + " ? * * *", triggerName))
        self.setTriggers(self.triggerList)

    def addChannelEventTrigger(self, channelUID, event):
        name = self.ruleName + "-" + channelUID + "-" + event
        triggerName = name + "_trigger"
        conditionName = name + "_condition"
        self.triggerList.append(ChannelEventTrigger(channelUID, triggerName))
        self.conditionList.append(ChannelEventCondition(triggerName, event, conditionName))
        self.setTriggers(self.triggerList)
        self.setConditions(self.conditionList)

    def _execute(self, auto):
        for shutterName in self.items:
            autoState = ir.get(prefix_auto + shutterName).getState().toString()
            if self.action == autoStateUp:
                    self.sendCommand(shutterName, "UP", auto)
            if self.action == autoStateDown:
                    self.sendCommand(shutterName, "DOWN", auto)
            if self.action == autoStateSun:
                if autoState == autoStateDown:
                    self.sendCommand(shutterName, "STOP", auto)
                    events.postUpdate(prefix_sunlit + shutterName, sunlitStateTrue)
                if autoState == autoStateUp:
                    events.postUpdate(prefix_sunlit + shutterName, sunlitStateFalse)
                if autoState == autoStateManual:
                    events.postUpdate(prefix_sunlit + shutterName, sunlitStateUnknown)

            events.postUpdate(prefix_auto + shutterName, self.action)

    def execute(self, module, input):
        self.logger.info("Executing Rule: " + self.ruleName + "; action: " + self.action + "; items: " + str(self.items))
        auto = self.shutterAutomationItem.getState().toString() == "ON"
        self._execute(auto)



#######################################################
# tests
class RulesTest():
    def __init__(self):
        self.logger = logging.getLogger(module_name + ":RulesTest")

    def sunExposureRuleTest(self):
        testExposureConfig = Yaml().load("""
            switch_rts_wohnzimmer_tuere:
                orientation: 240
                sun_openings:
                  - azimuth: 160
                  - azimuth: 330
        """)
        testExposure = {}
        for shutter in testExposureConfig:
            testExposure[shutter] = SunExposure(testExposureConfig[shutter])
        ser = SunExposureRule(testExposure,  "astro_sun_azimuth", "astro_sun_elevation", "switch_wetter_sonnig", "shutter_automation", True)

        # values for DOWN = 100, STOP = 50, UP = 0
        shutterName = "switch_rts_wohnzimmer_tuere"
        shutterItem = ir.get(shutterName)
        sunlitStateItem = ir.get(prefix_sunlit + shutterName)
        autoStateItem = ir.get(prefix_auto + shutterName)
        isSunnyItem = ir.get("switch_wetter_sonnig")

        events.postUpdate(isSunnyItem.getName(), "OFF")
        events.sendCommand(shutterItem.getName(), "DOWN")
        events.postUpdate(sunlitStateItem.getName(), sunlitStateFalse)
        events.postUpdate(autoStateItem.getName(), autoStateSun)

        # sunlit: true, state: SUN, weather: cloudy
        time.sleep(1)
        ser._execute(240, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "100"

        # sunlit: true, state: SUN, weather: sunny
        events.postUpdate(isSunnyItem.getName(), "ON")
        time.sleep(1)
        ser._execute(240, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "50"

        # sunlit: true, state: SUN, weather: cloudy
        events.postUpdate(isSunnyItem.getName(), "OFF")
        time.sleep(1)
        ser._execute(240, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "50"

        # sunlit: false, state: SUN, weather: cloudy
        ser._execute(60, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"

        # sunlit: true, state: DOWN, weather: sunny
        events.postUpdate(isSunnyItem.getName(), "ON")
        events.postUpdate(autoStateItem.getName(), autoStateDown)
        events.sendCommand(shutterItem.getName(), "DOWN")
        time.sleep(1)
        ser._execute(240, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "100"

        # sunlit: false, state: DOWN, weather: sunny
        ser._execute(60, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "100"

        # sunlit: true, state: UP, weather: sunny
        events.postUpdate(autoStateItem.getName(), autoStateUp)
        events.sendCommand(shutterItem.getName(), "UP")
        time.sleep(1)
        ser._execute(240, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"

        # sunlit: false, state: UP, weather: sunny
        ser._execute(60, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"

        # sunlit: true, state: MANUAL, weather: sunny
        events.postUpdate(autoStateItem.getName(), autoStateManual)
        events.postUpdate(sunlitStateItem.getName(), sunlitStateUnknown)
        events.sendCommand(shutterItem.getName(), "UP")
        time.sleep(1)
        ser._execute(240, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"

        # sunlit: true, state: SUN, weather: sunny, sunlitstat: unknown
        events.postUpdate(autoStateItem.getName(), autoStateSun)
        time.sleep(1)
        ser._execute(240, 30, True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"
        assert sunlitStateItem.getState().toString() == sunlitStateTrue

    def shutterScheduleRuleTest(self):
        shutterName = "switch_rts_wohnzimmer_tuere"
        shutterItem = ir.get(shutterName)
        sunlitStateItem = ir.get(prefix_sunlit + shutterName)
        autoStateItem = ir.get(prefix_auto + shutterName)

        ssrU = ShutterScheduleRule(autoStateUp, [shutterName], "testRule", "shutter_automation", True)
        ssrD = ShutterScheduleRule(autoStateDown, [shutterName], "testRule", "shutter_automation", True)
        ssrM = ShutterScheduleRule(autoStateManual, [shutterName], "testRule", "shutter_automation", True)
        ssrS = ShutterScheduleRule(autoStateSun, [shutterName], "testRule", "shutter_automation", True)

        events.sendCommand(shutterItem.getName(), "DOWN")
        events.postUpdate(sunlitStateItem.getName(), sunlitStateFalse)
        time.sleep(1)
        ssrU._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"
        assert autoStateItem.getState().toString() == autoStateUp
        assert sunlitStateItem.getState().toString() == sunlitStateFalse

        ssrD._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "100"
        assert autoStateItem.getState().toString() == autoStateDown
        assert sunlitStateItem.getState().toString() == sunlitStateFalse

        ssrM._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "100"
        assert autoStateItem.getState().toString() == autoStateManual
        assert sunlitStateItem.getState().toString() == sunlitStateFalse

        ssrS._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "100"
        assert autoStateItem.getState().toString() == autoStateSun
        assert sunlitStateItem.getState().toString() == sunlitStateUnknown

        events.postUpdate(sunlitStateItem.getName(), sunlitStateFalse)
        time.sleep(1)
        ssrU._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"
        assert autoStateItem.getState().toString() == autoStateUp
        assert sunlitStateItem.getState().toString() == sunlitStateFalse

        ssrM._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"
        assert autoStateItem.getState().toString() == autoStateManual
        assert sunlitStateItem.getState().toString() == sunlitStateFalse

        ssrS._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "0"
        assert autoStateItem.getState().toString() == autoStateSun
        assert sunlitStateItem.getState().toString() == sunlitStateUnknown

        ssrD._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "100"
        assert autoStateItem.getState().toString() == autoStateDown
        assert sunlitStateItem.getState().toString() == sunlitStateUnknown

        ssrS._execute(True)
        time.sleep(1)
        assert shutterItem.getState().toString() == "50"
        assert autoStateItem.getState().toString() == autoStateSun
        assert sunlitStateItem.getState().toString() == sunlitStateTrue

    def run(self):
        self.logger.info("TEST start")
        try:
            self.sunExposureRuleTest()
            self.shutterScheduleRuleTest()
        except Exception as e:
            self.logger.error(traceback.format_exc())

        self.logger.info("TEST end")

#######################################################
#######################################################
#######################################################
# Calendar

class Rules():
    def __init__(self, config, items):
        self.logger = logging.getLogger(module_name + ":Rules")
        self.config = config
        self.items = items
        self.rules = {}
        self.parseRules()

    def getRules(self, ruleName):
        return self.rules[ruleName]

    def parseRules(self):
        for rule_name in self.config:
            self.logger.info("RuleName: " + rule_name)
            config = self.config[rule_name]
            trigger_configs = config['triggers']
            actionItems = config['items']
            action = config['action']
            triggers = []
            # due to problem with the trigger wie have to create a rule for each channel_event trigger
            subList = []
            for trigger_config in trigger_configs:
                rule = ShutterScheduleRule(action,
                                           actionItems,
                                           rule_name + str(len(subList)),
                                           self.items['shutter_automation']
                                           );
                self.logger.debug("RuleName-generated: " + rule.getUID())
                self.logger.debug("Trigger_Config: " + str(trigger_config))
                if trigger_config.get('channel_event') != None:
                    tc = trigger_config.get('channel_event')
                    rule.addChannelEventTrigger(tc['channel'], tc['event'])
                elif trigger_config.get('cron') != None:
                    rule.addCronTrigger(trigger_config.get('cron'))
                subList.append(rule)
            self.rules[rule_name] = subList


class DailySchedules():
    def __init__(self, config, rules):
        self.logger = logging.getLogger(module_name + ":DailySchedules")
        self.config = config
        self.rules = rules
        self.schedules = {}
        self.parseDailySchedules()

    def getSchedules(self, scheduleName):
        return self.schedules[scheduleName]

    def parseDailySchedules(self):
        for scheduleName in self.config:
            config = self.config[scheduleName]
            rules = []
            for ruleName in config:
                for subRule in self.rules.getRules(ruleName):
                    rules.append(subRule)
            self.schedules[scheduleName] = rules

class Calendar():
    def __init__(self, config, schedules):
        self.logger = logging.getLogger(module_name + ":Calendar")
        self.config = config
        self.schedules = schedules

    def getDailyScheduleName(self):
        self.scheduleName = None
        now = Date()
        for calendarItem in self.config:
            # check if daily schedule exists:
            try:
                self.schedules.getSchedules(calendarItem['daily_schedule'])
            except Exception as e:
                self.logger.warn("Config Error" + str(e))
                raise e

            if calendarItem.get('cron') != None:
                if CronExpression("* * * " + calendarItem.get('cron')).isSatisfiedBy(now):
                    # don't break we want to test the config
                    if self.scheduleName == None:
                        self.scheduleName = calendarItem['daily_schedule']
            else: # has to be timerange
                df = DateFormat.getDateInstance(DateFormat.SHORT, Locale.GERMAN)
                fromDate = df.parse(calendarItem['timerange']['from'])
                toDate = df.parse(calendarItem['timerange']['to'])
                self.logger.debug(calendarItem['timerange']['from'])
                self.logger.debug(fromDate)
                self.logger.debug(calendarItem['timerange']['to'])
                self.logger.debug(toDate)
                self.logger.debug(now)
                if now.before(toDate) and now.after(fromDate):
                    # don't break we want to test the config
                    if self.scheduleName == None:
                        self.scheduleName = calendarItem['daily_schedule']

        self.logger.info("Daily Schedule: " + str(self.scheduleName))
        return self.scheduleName

    def getTodaysRules(self):
        return self.schedules.getSchedules(self.getDailyScheduleName())

    def loadTodaysRules(self):
        for rule in self.getTodaysRules():
            automationManager.addRule(rule)


#######################################################
class DailyReloadRule(SimpleRule):
    def __init__(self):
        self.triggers = [CronTrigger("0 10 0 ? * * *", "reloadAtMidnight")]

    def execute(self, module, input):
        automationManager.removeAll()
        addAllRules()


#######################################################
class CalendarTest():
    def __init__(self):
        self.logger = logging.getLogger(module_name + ":CalendarTest")

    def calendarTest(self, schedules):
        self.logger.info("calendarTest")

        calendar = Calendar(Yaml().load("""
            - desc: "Sommerferien"
              timerange: {from: "12.06.2017", to: "16.08.2017" }
              daily_schedule: vacation
            - desc: "Weekend"
              cron: "? * 7,1 *"
              daily_schedule: weekend
            - desc: "Workdays"
              cron: "? * 2-6 *"
              daily_schedule: workday
        """), schedules).getDailyScheduleName()

    def dailySchedulesTest(self, rules):
        self.logger.info("dailySchedulesTest")

        schedules = DailySchedules(Yaml().load("""
              weekend:
                - kids_evening
                - kids_open
              workday:
                - kids_open
              vacation:
                - kids_open
        """), rules)
        return schedules

    def rulesTest(self):
        self.logger.info("rulesTest")

        rules = Rules(Yaml().load("""
            kids_evening:
                triggers:
                  - cron: '0 30 19'
                action: MANUAL
                items:
                  - switch_rts_kinder_gross
            kids_open:
                triggers:
                  - cron: '0 30 20'
                  - channel_event: {channel: 'astro:sun:local:nauticDusk#event', event: 'START'}
                action: SUN
                items:
                  - switch_rts_kinder_gross
        """), {'shutter_automation': 'shutter_automation'})
        return rules

    def run(self):
        self.logger.info("TEST start")
        try:
            rules = self.rulesTest()
            schedules = self.dailySchedulesTest(rules)
            self.calendarTest(schedules)

        except Exception as e:
            self.logger.error(traceback.format_exc())

        self.logger.info("TEST end")

#######################################################
#######################################################
#######################################################
#fileWatcher

automationDirPath = FileSystems.getDefault().getPath(automationDir)
configFileWatcher = FileSystems.getDefault().newWatchService()
configFileWatcherKey = automationDirPath.register(configFileWatcher, StandardWatchEventKinds.ENTRY_MODIFY);

def fileWatcher():
    logger = logging.getLogger(module_name + ":fileWatcher")
    logger.info("Start Watching")
    try:
        while True:
            key = configFileWatcher.take()
            logger.info("configFileWatcher got key")
            for event in key.pollEvents():
                filename = event.context()
                logger.debug(filename)
                if str(filename) == shuttersFileName or str(filename) == scheduleFileName:
                    logger.info("File " + str(filename) + " changed. Reloading config")
                    restart()
            key.reset()
    except InterruptedException:
        logger.info("Stop Watching")
        Thread.currentThread().interrupt()

#http://www.jython.org/jythonbook/en/1.0/Concurrency.html
fileWatcherThread = Thread(target=lambda: fileWatcher())


#######################################################
#######################################################
#######################################################
# __main__

def addAllRules():
    for rule in globalRules:
        automationManager.addRule(rule)
    calendar.loadTodaysRules()

def runTests():
        #ShutterTest().run()
        #RulesTest().run()
        #CalendarTest().run()
        pass

def load():
    global config
    global calendar
    global globalRules

    globalRules = []
    config = Config()

    initStateItems()

    setupSunExposureRule(config.getSunExposure(), config.getItems())

    calendar = Calendar(config.getCalendar(),
                        DailySchedules(config.getDailySchedules(),
                                       Rules(config.getRules(),
                                             config.getItems())))
    globalRules.append(DailyReloadRule())
    addAllRules()

def restart():
    automationManager.removeAll()
    load()


#######################################################
# script load/unload hooks

def scriptLoaded(id):
    try:
        #runTests()

        load()
        fileWatcherThread.start()

        # during development, delete in production
        #events.postUpdate("switch_wetter_sonnig", "ON")
        #events.postUpdate("shutter_automation", "ON")
        #initStateItems(True, {prefix_auto: autoStateDown, prefix_sunlit: sunlitStateFalse})


    except Exception as e:
        logger.error(traceback.format_exc())

def scriptUnloaded():
    fileWatcherThread.interrupt()
    configFileWatcherKey.cancel()
