# originally copied from https://github.com/OH-Jython-Scripters/openhab2-jython/blob/master/Core/automation/jsr223/core/000_startup_delay.py

from time import sleep
from org.slf4j import LoggerFactory

logger = LoggerFactory.getLogger("jython.001_startup_delay")

logger.info("Checking for initialized context")

while True:
    try:
        scriptExtension.importPreset("RuleSupport")
        if automationManager is not None:
            break
    except:
        logger.info("Context not initialized yet... waiting 10s before checking again")
        sleep(10)

logger.info("Context initialized... waiting 30s before allowing scripts to load")
sleep(30)
logger.info("Complete")

