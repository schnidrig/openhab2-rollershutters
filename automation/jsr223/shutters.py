# Copyright (c) 2017-2018 by Christian Schnidrig.

# see also:
# https://github.com/eclipse/smarthome/tree/master/bundles/automation/org.eclipse.smarthome.automation.module.script.rulesupport/src/main/java/org/eclipse/smarthome/automation/module/script/rulesupport
# https://github.com/eclipse/smarthome/tree/master/bundles/automation/org.eclipse.smarthome.automation.module.core/src/main/java/org/eclipse/smarthome/automation/module/core/handler

# jython imports
from org.slf4j import LoggerFactory
import uuid
import math
import sys
import traceback
import time
from threading import Thread
 
# java imports
#from org.eclipse.smarthome.core.scheduler import CronExpression
from org.quartz import CronExpression
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
logger_name = "jython." + module_name
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
automationDir = '/etc/openhab2/automation'

shuttersFileName = 'shutters.yml'
scheduleFileName = 'shutter_schedule.yml'
shuttersFile = automationDir + '/' + shuttersFileName
scheduleFile = automationDir + '/' + scheduleFileName

#######################################################
# some globals
config = None
calendar = None

# default logger
logger = LoggerFactory.getLogger(logger_name)

# globalRules
globalRules = None

#######################################################
#######################################################
#######################################################
# config
class Config():
    def __init__(self):
        self.logger = LoggerFactory.getLogger(logger_name + ".Config")
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
    logger = LoggerFactory.getLogger(logger_name + ".initStateItems")
    logger.info("Initializing")
    if states == None:
        states = {prefix_auto: autoStateDown, prefix_sunlit: sunlitStateFalse}
    for item_name in config.getShutters():
        for prefix in states:
            item = ir.get(prefix + item_name)
            if item == None:
                logger.error("Item: " + prefix + item_name + " not found.")
            elif str(item.getState()) == "NULL" or force:
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
# Condition

def itemStateCondition(itemName, operator, state, conditionName=None):
    logger = LoggerFactory.getLogger(logger_name + ".ItemStateCondition")
    conditionName = normalize_name(conditionName)
    logger.info("Condition: " + conditionName)
    result = ConditionBuilder.create()\
        .withId(conditionName)\
        .withLabel(conditionName)\
        .withTypeUID("core.ItemStateCondition")\
        .withConfiguration(Configuration({
        "itemName": itemName,
        "operator": operator,
        "state": state
        }))\
        .build()
    logger.debug(result.toString())
    return result

#######################################################
#######################################################
#######################################################
# Triggers

def cronTrigger(cronExpression, triggerName=None):
    logger = LoggerFactory.getLogger(logger_name + ".CronTrigger")
    triggerName = normalize_name(triggerName)
    return TriggerBuilder.create()\
        .withId(triggerName)\
        .withLabel(triggerName)\
        .withTypeUID("timer.GenericCronTrigger")\
        .withConfiguration(Configuration({"cronExpression": cronExpression}))\
        .build()

def channelEventTrigger(channelUID, event, triggerName=None):
    logger = LoggerFactory.getLogger(logger_name + ".ChannelEventTrigger")
    triggerName = normalize_name(triggerName)
    logger.debug("Trigger: " + triggerName + "; channel: " + channelUID)
    config = { "channelUID": channelUID }
    config["event"] = event
    return TriggerBuilder.create()\
        .withId(triggerName)\
        .withLabel(triggerName)\
        .withTypeUID("core.ChannelEventTrigger")\
        .withConfiguration(Configuration(config))\
        .build()

def itemStateChangeTrigger(itemName, state=None, triggerName=None):
    logger = LoggerFactory.getLogger(logger_name + ".ItemStateChangeTrigger")
    triggerName = normalize_name(triggerName)
    config = { "itemName": itemName }
    if state is not None:
        config["state"] = state
    return TriggerBuilder.create()\
        .withId(triggerName)\
        .withLabel(triggerName)\
        .withTypeUID("core.ItemStateUpdateTrigger")\
        .withConfiguration(Configuration(config))\
        .build()

#######################################################
#######################################################
#######################################################
# Shutters

#######################################################
class Horizon():
    def __init__(self, orientation, config):
        self.logger = LoggerFactory.getLogger(logger_name + ".Horizon")
        self.elevation = config['elevation']
    def getElevationAtAzimuth(self, azimuth):
        return self.elevation


#######################################################

#===============================================================================
# p = penetration / P = penetration with e = profileAngle 
# h = height
# e = elevation
# a = azimuth
# PA = profileAngle

# p = cos(e) r 
# h = sin(e) r
# h / p = tan(e)
# p = h / tan(e)

# -------
# P = h / tan (PA)
# p = h / tan(e)
# P = p cos(a) = (h / tan(e) ) cos(a) = h /tan(PA)

# cos(a2) / tan(e2) = 1/tan(PA)
# PA = atan(tan(e)/cos(a))

#===============================================================================

class HLine():
    def __init__(self, orientation, config):
        self.logger = LoggerFactory.getLogger(logger_name + ".HLine")
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
                math.cos( math.radians( azimuth - self.orientation ))
            )
        )
 
    def _getElevationAtAzimuth(self, azimuth, profileAngle):
        self.logger.debug( str(azimuth) + ";" + str(profileAngle) )
        return math.degrees(
            math.atan(
                math.cos( math.radians(azimuth-self.orientation) )
                *
                math.tan( math.radians(profileAngle) )
            )
        ) 

#######################################################

# tan e = tan e0 - tan g * tan a

# tan g = (tan e1 - tan e2) / (tan a2 - tan a1)

class Line(HLine):
    def __init__(self, orientation, config):
        self.logger = LoggerFactory.getLogger(logger_name + ".Line")
        self.orientation = orientation
        a1 = math.radians(config[0]['azimuth']-self.orientation)
        e1 = math.radians(self._calculateProfileAngle(config[0]['elevation'], config[0]['azimuth']))
        angle = config[0].get('angle')
        if (angle != None):
            self.tan_gamma = math.tan(math.radians(angle))
        else:
            a2 = math.radians(config[1]['azimuth']-self.orientation)
            e2 = math.radians(self._calculateProfileAngle(config[1]['elevation'], config[1]['azimuth']))
            self.tan_gamma = (math.tan(e1) - math.tan(e2)) / (math.tan(a2) - math.tan(a1))
        self.tan_e0 =  math.tan(e1) + self.tan_gamma * math.tan(a1)                                                 
        self.logger.debug("Gamma: " + str(math.degrees(math.atan(self.tan_gamma))) + "; E0:" + str(math.degrees(math.atan(self.tan_e0))))
        self.logger.debug(str(self.tan_gamma) + "/" + str(self.tan_e0))

    def getElevationAtAzimuth(self, azimuth):
        e = math.atan(self.tan_e0 - self.tan_gamma * math.tan(math.radians(azimuth-self.orientation)))
        return self._getElevationAtAzimuth(azimuth, math.degrees(e))

#######################################################
class SunExposure():
    def __init__(self, config):
        self.logger = LoggerFactory.getLogger(logger_name + ".SunExposure")
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
        self.logger.debug(str(self.config))
        self.logger.debug(str(sections))
        section = None
        for i in sections:
            self.logger.debug("i: " + str(i) + "; " + str(azimuth))
            if float(i) > float(str(azimuth)):
                break
            else:
                section = i
        self.logger.debug(str(section))
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
        self.logger = LoggerFactory.getLogger(logger_name + ".ShutterTest")

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
        

        # two measurements back and forth
        hline3 = HLine(150, Yaml().load("{ azimuth: 145, elevation: 62.5 }"))
        hline4 = HLine(150, Yaml().load("{ azimuth: 198.3, elevation: 52.4 }"))

        t5 = hline3.getElevationAtAzimuth(198.3)
        t6 = hline4.getElevationAtAzimuth(145)
        #self.logger.info("t5:" + str(t5))
        #self.logger.info("t6:" + str(t6))
        assert round(t5) == 52
        assert round(t6) == 63


    
    def lineTest(self):
        self.logger.info("lineTest")
        line1 = Line(60, Yaml().load("""
             - { azimuth: 120, elevation: 35.82 }
             - { azimuth: 110, elevation: 49 }
             """))
        line = Line(240, Yaml().load("""
             - { azimuth: 197.28, elevation: 39.54 }
             - { azimuth: 227, elevation: 59 }
             """))
        line3 = Line(240, Yaml().load("""
             - { azimuth: 197.28, elevation: 39.54 }
             - { azimuth: 199.52, elevation: 41.56 }
             """))
        line4 = Line(240, Yaml().load("""
             - { azimuth: 197.28, elevation: 39.54, angle: -35 }
             """))

        # gäste
        line5 = Line(240, Yaml().load("""
             - { azimuth: 174.88, elevation: 30.3 }
             - { azimuth: 189.58, elevation: 53.66 }
             """))
        self.logger.debug(line.getElevationAtAzimuth(240))
        self.logger.debug(line.getElevationAtAzimuth(224))
        self.logger.debug(line.getElevationAtAzimuth(227))
        self.logger.debug(line.getElevationAtAzimuth(200))
        self.logger.debug(line.getElevationAtAzimuth(199.52))
        self.logger.debug(line.getElevationAtAzimuth(180))
        self.logger.debug(line.getElevationAtAzimuth(170))
        self.logger.debug(line.getElevationAtAzimuth(160))
        self.logger.debug(line.getElevationAtAzimuth(150))
        self.logger.debug(line.getElevationAtAzimuth(290))
        self.logger.debug(line.getElevationAtAzimuth(300))
        self.logger.debug(line.getElevationAtAzimuth(310))
        self.logger.debug(line.getElevationAtAzimuth(320))
        self.logger.debug(line.getElevationAtAzimuth(330))
        self.logger.debug(line.getElevationAtAzimuth(175))
        self.logger.debug(line5.getElevationAtAzimuth(181.68))

        assert round(line.getElevationAtAzimuth(240)) == 62
        assert round(line.getElevationAtAzimuth(224)) == 58
        assert round(line.getElevationAtAzimuth(227)) == 59
        assert round(line.getElevationAtAzimuth(199.52)) == 42
        
        assert round(line.getElevationAtAzimuth(174)) == 0

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

#######################################################
class JythonSimpleRule(SimpleRule):
    def execute(self, module, input):
        try:
            self._execute(module, input)
        except:
            logger.error(traceback.format_exc())

class ShutterBaseRule(JythonSimpleRule):
    def __init__(self, shutterAutomationItem, testing=False, forced=False):
        self.testing = testing
        self.forced = forced
        if ir.get(shutterAutomationItem) == None:
            self.logger.error("Item: " + shutterAutomationItem + " not found.")
        self.shutterAutomationItem = shutterAutomationItem

    def sendCommand(self, shutterName, state, auto):
        if not (auto or self.forced):
            self.logger.info("Auto(OFF): Not sending command: " + shutterName + "=" + state)
        else:
            if self.forced:
                self.logger.info("Auto(forced): sending command: " + shutterName + "=" + state)
            else:
                self.logger.info("Auto(ON): sending command: " + shutterName + "=" + state)
            if self.testing:
                events.sendCommand(shutterName, state if state != "STOP" else "50")
            else:
                events.sendCommand(shutterName, state)

#######################################################
# Sun Exposure Rule

class SunExposureRule(ShutterBaseRule):
    def __init__(self, exposure, azimuthItem, elevationItem, isSunnyItem, shutterAutomationItem, testing=False, forced=False):
        #super(ShutterBaseRule, self).__init__(shutterAutomationItem, testing)
        self.logger = LoggerFactory.getLogger(logger_name + ".SunExposureRule")
        ShutterBaseRule.__init__(self, shutterAutomationItem, testing, forced)
        self.exposure = exposure
        if ir.get(elevationItem) == None:
            self.logger.error("Item: " + elevationItem + " not found.")
        self.elevationItem = elevationItem
        if ir.get(isSunnyItem) == None:
            self.logger.error("Item: " + isSunnyItem + " not found.")
        self.isSunnyItem = isSunnyItem
        self.setTriggers([itemStateChangeTrigger(azimuthItem)])
        self.setName(module_name + ":SunExposureRule")
        self.setDescription("Calculates if a rollershutter is exposed to sunlight.")

    def run(self, azimuth, elevation, auto):
        isSunny = ir.get(self.isSunnyItem).getState().toString() == "ON"
        self.logger.info("azimuth: " + str(azimuth) + "; elevation: " + str(elevation) + "; isSunny: " + str(isSunny))

        for shutterName in self.exposure:
            shutterAutoState = ir.get(prefix_auto + shutterName).getState().toString()
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

    def _execute(self, module, input):
        self.logger.debug("Executing Exposure Rule: ")
        self.logger.debug(str(input))
        azimuth = float(str(input['state']))
        elevation = float(ir.get(self.elevationItem).getState().toString())
        auto = ir.get(self.shutterAutomationItem).getState().toString() == "ON"
        self.logger.debug("shutter_automation is: " + str(auto))
        self.run(azimuth, elevation, auto)


def setupSunExposureRule(exposureConfig, items):
    logger = LoggerFactory.getLogger(logger_name + ".setupSunExposureRule")
    logger.info("creating rule")
    exposure = {}
    for shutter in exposureConfig:
        exposure[shutter] = SunExposure(exposureConfig[shutter])
    globalRules.append(SunExposureRule(exposure, items['azimuth'], items['elevation'], items['weather_sunny'], items['shutter_automation']))

#######################################################
# Shutter Rule

class ShutterScheduleRule(ShutterBaseRule):
    def __init__(self, action, items, ruleName, shutterAutomationItem, description = "", testing=False, forced=False):
        ShutterBaseRule.__init__(self, shutterAutomationItem, testing, forced)
        self.logger = LoggerFactory.getLogger(logger_name + ".ShutterScheduleRule")
        self.action = action
        self.items = items
        self.triggerList = []
        self.conditionList = []
        self.ruleName = normalize_name(ruleName, "")
        self.prefixedRuleName = normalize_name(self.ruleName)
        self.setName(module_name + ":ShutterScheduleRule:" + ruleName)
        self.setDescription(description)

    def addCronTrigger(self, schedule):
        name = self.ruleName + "-cron:" + str(schedule).replace("*", "s").replace("?", "q").replace(" ", "l").replace("/", "x")
        triggerName = name + "_trigger"
        self.triggerList.append(cronTrigger(schedule + " ? * * *", triggerName))
        self.setTriggers(self.triggerList)

    def addChannelEventTrigger(self, channelUID, event):
        name = self.ruleName + "-" + channelUID + "-" + event
        triggerName = name + "_trigger"
        conditionName = name + "_condition"
        self.triggerList.append(channelEventTrigger(channelUID, event, triggerName))
        self.setTriggers(self.triggerList) 
 
    def addItemStateCondition(self, config):
        conditionName = self.ruleName + "-" + config['item_name'] + "_"  + config['state']
        self.conditionList.append(itemStateCondition(config['item_name'], config['operator'], config['state'], conditionName))
        self.setConditions(self.conditionList)

    def run(self, auto):
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

    def _execute(self, module, input):
        self.logger.info("Executing Rule: " + self.ruleName + "; action: " + self.action + "; items: " + str(self.items))
        auto = ir.get(self.shutterAutomationItem).getState().toString() == "ON"
        self.logger.debug("shutter_automation is: " + str(auto))
        self.run(auto)

#######################################################
# tests
class RulesTest():
    def __init__(self):
        self.logger = LoggerFactory.getLogger(logger_name + ".RulesTest")

    def sunExposureRuleTest(self):
        testExposureConfig = Yaml().load("""
            shutter_living:
                orientation: 240
                sun_openings:
                  - azimuth: 160
                  - azimuth: 330
        """)
        testExposure = {}
        for shutter in testExposureConfig:
            testExposure[shutter] = SunExposure(testExposureConfig[shutter])
        ser = SunExposureRule(testExposure,  "astro_sun_azimuth", "astro_sun_elevation", "weather_sunny", "shutter_automation", True)

        # values for DOWN = 100, STOP = 50, UP = 0
        shutterName = "shutter_living"
        shutterItem = ir.get(shutterName)
        sunlitStateItem = ir.get(prefix_sunlit + shutterName)
        autoStateItem = ir.get(prefix_auto + shutterName)
        isSunnyItem = ir.get("weather_sunny")

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
        shutterName = "shutter_living"
        shutterItem = ir.get(shutterName)
        sunlitStateItem = ir.get(prefix_sunlit + shutterName)
        autoStateItem = ir.get(prefix_auto + shutterName)

        ssrU = ShutterScheduleRule(autoStateUp, [shutterName], "testRule", "shutter_automation", "", True)
        ssrD = ShutterScheduleRule(autoStateDown, [shutterName], "testRule", "shutter_automation", "", True)
        ssrM = ShutterScheduleRule(autoStateManual, [shutterName], "testRule", "shutter_automation", "", True)
        ssrS = ShutterScheduleRule(autoStateSun, [shutterName], "testRule", "shutter_automation", "", True)

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
        self.logger = LoggerFactory.getLogger(logger_name + ".Rules")
        self.config = config
        self.items = items
        self.rules = {}
        self.parseRules()

    def getRule(self, ruleName):
        return self.rules[ruleName]

    def parseRules(self):
        for rule_name in self.config:
            config = self.config[rule_name]
            forced = config.get('forced')
            if forced == None:
                forced = False
            self.logger.info("Parser: found rule: " + rule_name + ("(forced)" if forced else ""))
            trigger_configs = config['triggers']
            condition_configs = config.get('conditions')
            if condition_configs == None:
                condition_configs = []
            actionItems = config['items']
            action = config['action']
            triggers = []
            rule = ShutterScheduleRule(action,
                                       actionItems,
                                       rule_name,
                                       self.items['shutter_automation'],
                                       config['desc'],
                                       forced=forced
                                       );
            for triggerConfig in trigger_configs:
                self.logger.debug("Trigger_Config: " + str(triggerConfig))
                triggerType = triggerConfig.keys()
                if len(triggerType) > 0:
                    triggerType = triggerType[0]                 
                    if triggerType == 'channel_event':
                        tc = triggerConfig.get('channel_event')
                        rule.addChannelEventTrigger(tc['channel'], tc['event'])
                    elif triggerType == 'cron':
                        rule.addCronTrigger(triggerConfig.get('cron'))
                    else:
                        self.logger.error("Unknown trigger type: " + str(triggerType))                    
            for conditionConfig in condition_configs:
                self.logger.debug("Condition Config: " + str(conditionConfig))
                conditionType = conditionConfig.keys()
                if len(conditionType) > 0:
                    conditionType = conditionType[0]                   
                    if conditionType == "item_state":
                        rule.addItemStateCondition(conditionConfig.get('item_state'))
                    else:
                        self.logger.error("Unknown condition type: " + str(conditionType))                    
            self.rules[rule_name] = rule

class DailySchedules():
    def __init__(self, config, rules):
        self.logger = LoggerFactory.getLogger(logger_name + ".DailySchedules")
        self.config = config
        self.rules = rules
        self.schedules = {}
        self.parseDailySchedules()

    def getSchedules(self, scheduleName):
        if scheduleName != None:
            return self.schedules[scheduleName]
        else:
            return {}

    def parseDailySchedules(self):
        for scheduleName in self.config:
            self.logger.info("Parser: found daily schedule: " + scheduleName)
            config = self.config[scheduleName]
            rules = []
            for ruleName in config:
                rules.append(self.rules.getRule(ruleName))
            self.schedules[scheduleName] = rules

class Calendar():
    def __init__(self, config, schedules):
        self.logger = LoggerFactory.getLogger(logger_name + ".Calendar")
        self.config = config
        self.schedules = schedules

    def getDailyScheduleName(self):
        self.scheduleName = None
        now = Date()
        for calendarItem in self.config:
            self.logger.info("Parser: found calendar item: " + str(calendarItem))
            # check if daily schedule exists:
            try:
                self.schedules.getSchedules(calendarItem['daily_schedule'])
            except Exception as e:
                self.logger.warn("Config Error" + str(e))
                raise e

            if calendarItem.get('cron') != None:
                cronExpression = "* * * " + calendarItem.get('cron')
                self.logger.debug(cronExpression)
                self.logger.debug(str(now))
                if CronExpression(cronExpression).isSatisfiedBy(now):
                    # don't break we want to test the config
                    if self.scheduleName == None:
                        self.scheduleName = calendarItem['daily_schedule']
            else: # has to be timerange
                df = DateFormat.getDateInstance(DateFormat.SHORT, Locale.GERMAN)
                fromDate = df.parse(calendarItem['timerange']['from'])
                toDate = df.parse(calendarItem['timerange']['to'])
                self.logger.debug(calendarItem['timerange']['from'])
                self.logger.debug(str(fromDate))
                self.logger.debug(calendarItem['timerange']['to'])
                self.logger.debug(str(toDate))
                self.logger.debug(str(now))
                if now.before(toDate) and now.after(fromDate):
                    # don't break we want to test the config
                    if self.scheduleName == None:
                        self.scheduleName = calendarItem['daily_schedule']

        if self.scheduleName == None:
            self.logger.warn("Todays daily schedule: " + str(self.scheduleName))
        else:
            self.logger.info("todays daily schedule: " + str(self.scheduleName))
        return self.scheduleName

    def getTodaysRules(self):
        return self.schedules.getSchedules(self.getDailyScheduleName())

    def loadTodaysRules(self):
        rules = self.getTodaysRules()
        self.logger.info("loading todays rules...")
        for rule in rules:
            automationManager.addRule(rule)


#######################################################
class DailyReloadRule(JythonSimpleRule):
    def __init__(self):
        self.triggers = [cronTrigger("0 10 0 ? * * *", "reloadAtMidnight")]
        self.setName(module_name + ":DailyReloadRule")
        self.setDescription("Determines each day, which daily schedule to run.")


    def _execute(self, module, input):
        automationManager.removeAll()
        addAllRules()

#######################################################
class CalendarTest():
    def __init__(self):
        self.logger = LoggerFactory.getLogger(logger_name + ".CalendarTest")

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
                  - shutter_living
            kids_open:
                triggers:
                  - cron: '0 30 20'
                  - channel_event: {channel: 'astro:sun:local:nauticDusk#event', event: 'START'}
                action: SUN
                items:
                  - shutter_living
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
# tests
class MiscTest():
    def __init__(self):
        self.logger = LoggerFactory.getLogger(logger_name + ".MiscTest")

    # Test for bug in CronExpression
    def cronTest(self):
        self.logger.info("cronTest")
        dateFormat = DateFormat.getDateInstance(DateFormat.SHORT, Locale.GERMAN)
        assert CronExpression("* * * ? * SAT,SUN *").isSatisfiedBy(dateFormat.parse("29.07.2017"))
        assert CronExpression("* * * ? * SAT,SUN *").isSatisfiedBy(dateFormat.parse("30.07.2017"))
        assert CronExpression("* * * ? * SAT,SUN *").isSatisfiedBy(dateFormat.parse("03.09.2017"))

    def run(self):
        self.logger.info("TEST start")
        try:
            self.cronTest()
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
    logger = LoggerFactory.getLogger(logger_name + ".fileWatcher")
    logger.info("Start watching config files")
    try:
        while True:
            key = configFileWatcher.take()
            logger.info("configFileWatcher got key")
            for event in key.pollEvents():
                filename = event.context()
                logger.debug(filename)
                if str(filename) == shuttersFileName or str(filename) == scheduleFileName:
                    logger.info("File " + str(filename) + " changed. Reloading config")
                    try:
                        restart()
                    except Exception as e:
                        logger.error("Failed reloading rules.")
                        logger.error(traceback.format_exc())
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
        #MiscTest().run()
        ShutterTest().run()
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
        fileWatcherThread.start()
        #runTests()

        load()

        # during development, delete in production
        #events.postUpdate("weather_sunny", "ON")
        #events.postUpdate("shutter_automation", "ON")
        #initStateItems(True, {prefix_auto: autoStateSun, prefix_sunlit: sunlitStateFalse})

    #except Exception as e:
    except:
        logger.error(traceback.format_exc())

def scriptUnloaded():
    fileWatcherThread.interrupt()
    configFileWatcherKey.cancel()

