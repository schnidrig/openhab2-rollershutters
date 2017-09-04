# inspired by https://raw.githubusercontent.com/steve-bate/openhab2-jython/5cf5b09d1f6d492358207fde5ad14f4e7a2689b9/lib/openhab/log.py
# 2017 Sept: changed to use Log4j2 instead of slf4j.

# this script is not needed if you already use the library by Steve Bate: https://github.com/steve-bate/openhab2-jython/tree/master

import logging
from org.apache.logging.log4j import Logger, LogManager

class Log4j2Handler(logging.Handler):
    def emit(self, record):
        message = self.format(record)
        logger_name = record.name
        if record.name == "root":
            logger_name = LogManager.ROOT_LOGGER_NAME
        logger = LogManager.getLogger(logger_name)
        level = record.levelno
        if level == logging.DEBUG:
            logger.debug(message)
        elif level == logging.INFO:
            logger.info(message)
        elif level == logging.WARN:
            logger.warn(message)
        elif level == logging.ERROR:
            logger.error(message)
        elif level == logging.CRITICAL:
            logger.fatal(message)
        else:
            logger.fatal("unknown logger level: " + str(level))

def scriptLoaded(id):
    handler = Log4j2Handler()
    logging.root.setLevel(logging.DEBUG)
    logging.root.handlers = [handler]

def scriptUnloaded():
    logging.root.handlers = []
