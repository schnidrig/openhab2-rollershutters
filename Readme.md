# Rollershutter Automation Script

This is a script written for Openhab2. It is written in Jython and depends on the new jsr223 scripting feature. See [jsr223](http://docs.openhab.org/configuration/jsr223.html) for more information.

## Features

- calendar specifying which daily schedule to run on which day.
- daily schedules like "workday" "weekend" "vaction" defining which rules are to be run a each type of day
- rules defining when to run what action on which items
- shading logic: for each window calculate when it is sunlit based on astro binding info and a shading model for each window.
- take into account weather binding info or sun sensor
- master automation ON/OFF switch
- entirely configured through yaml


## Config

The examples are not from an actual running config. There may very well be inconsistencies.

### Calendar

The calendar defines which daily schedule should run on what day. E.g. you may define daily schedules like workday, weekend and vacation:

    calendar:
      - desc: "Summer Vacation"
        timerange: {from: "12.06.2017", to: "25.06.2017" }
        daily_schedule: vacation
      - desc: "Weekends"
        cron: "? * 7,1 *"
        daily_schedule: weekend
      - desc: "Workdays"
        cron: "? * 2-6 *"
        daily_schedule: workday

It is possible to use timeranges or cron expressions ( without seconds, minutes, hours ) syntax from org.eclipse.smarthome.core.scheduler.CronExpression. (compatible with [Quarz](https://quartz-scheduler.org/), see [CronExpression](http://www.quartz-scheduler.org/api/2.2.1/org/quartz/CronExpression.html) )
The first match wins.

### Daily Schedules

Daily schedules define lists of rules that are to be run on a specific type of day.

    daily_schedules:
      weekend:
        - open_weekend
        - kids_evening
        - close_dusk
      workday:
        - open_workday
        - kids_open
        - kids_evening
        - close_dusk
      vacation:
        - open_workday
        - kids_open
        - close_dusk

### Rules

Rules define triggers after which a set of rollershutters should be put into a specific state (action)

    rules:
      open_weekend:
        desc: "Open all on weekends"
        triggers:
          - cron: '0 0 9'
        action: SUN
        items:
          - shutter_kitchen
          - shutter_office
          - shutter_living
          - shutter_kids
          - shutter_bedroom
      open_workday:
        desc: "Open all on workdays"
        triggers:
          - cron: '0 0 7'
        action: SUN
        items:
          - shutter_kitchen
          - shutter_office
          - shutter_living
          - shutter_bedroom
      kids_evening:
        desc: "Kids: close manually when kids are ready and don't open after sunset when kids already asleep"
        triggers:
          - cron: '0 30 19'
        action: MANUAL
        items:
          - shutter_kids
      kids_open:
        desc: "Kids: open in the morning"
        triggers:
          - cron: '0 0 8'
        action: SUN
        items:
          - shutter_kids
      close_dusk:
        desc: "dusk: shut shutters after nightfall or at 22:00"
        triggers:
          - channel_event: {channel: 'astro:sun:local:nauticDusk#event', event: 'START'}
          - cron: '0 0 22'
        action: DOWN
        items:
          - shutter_kitchen
          - shutter_office
          - shutter_living
          - shutter_kids
          - shutter_bedroom

#### actions / rollershutter states


State | Description
------|-------------
DOWN|rollershutter is closed and will not open no matter if the sun shines or not
UP|rollershutter is open and will not close no matter if the sun shines or not
SUN|rollershutter is open unless window is exposed to sun shine. (weather dependent)
MANUAL|rollershutter is in manual mode

### Items

A set of Items that have to exist and are used by the rollershutter script.

    items:
      azimuth: astro_sun_azimuth
      elevation: astro_sun_elevation
      weather_sunny: weather_sunny
      shutter_automation: shutter_automation

- `azimuth` & `elevation`: Items linked to the Astro binding e.g. defined as:

    Number astro_sun_elevation  "Elevation [%.0f]" { channel="astro:sun:local:position#elevation" }
    Number astro_sun_azimuth    "Azimuth [%.0f]"   { channel="astro:sun:local:position#azimuth" }

- `weather_sunny`: Switch item which is ON when the sun is shining. Could be from a weather binding or a sensor.

- `shutter_automation`: Switch item which allows for turning on/off the rollershutter automation.

### Sun Exposure

This allows for the definition of when a window is sunlit and should be closed (provided the sun is shining)

    sun_exposure:
      shutter_living:
        orientation: 240
        sun_openings:
          - azimuth: 160
            below:
              - { azimuth: 240, elevation: 60}
            above:
              - { elevation: 5}
          - azimuth: 240
            below:
              - { azimuth: 240, elevation: 60}
              - { azimuth: 280, elevation: 10}
            above:
              - { azimuth: 240, elevation: 3}
          - azimuth: 330
      shutter_office:
        orientation: 150
        sun_openings:
          - azimuth: 160
          - azimuth: 330

- `orientation`: in which direction faces the window (perpendicular to the window's surface) E.g. 180 would mean a window facing south.
- `sun_openings`: series of sections (between two azimuths) where the sun is limited by two uniform obstacles from above and below.
- `above` & `below`: top and bottom limitation for the elevation of the sun beyond which the sun does not shine into the window.

#### Defining horizontal obstacles

- Obstacle following the horizon. E.g tree line far away.


    - { elevation: 5}

- Obstacle describing strait horizontal line. E.g a balcony above the window parallel to the window's surface. Azimuth & elevation can be any point on that line    


    - { azimuth: 240, elevation: 60}

- Obstacle describing arbitrary strait line between two points. E.g. the roof partly shading the window.


    - { azimuth: 240, elevation: 60}
    - { azimuth: 280, elevation: 30}


- The last azimuth defines the end of the last section:


    - azimuth: 330

## Installation

 - Make sure you have enabled the new rules support and installed the jython library for jsr223 support. (put jython-standalone-2.7.0.jar from http://www.jython.org/downloads.html into the boot folder: /usr/share/openhab2/runtime/lib/boot/)
 - Download http://central.maven.org/maven2/org/yaml/snakeyaml/1.18/snakeyaml-1.18.jar and install it in the addons folder: /usr/share/openhab2/addons.

 - Install the contents of this repo in the automation folder: /etc/openhab2/automation/jsr223/
 - Edit shutter_schedule.yml and shutters.yml according to your needs.

 - In case your installation paths differ, change the corresponding paths in shutter.py

 - Create state items. You need two for each shutter. e.g. if you hava a shutter called `shutter_kitchen` define two additional Strings with the prefixes `state_auto_` and `state_sunlit_`. Make them persistent.

    Rollershutter shutter_kitchen         "RTS Kitchen"         (mysql)  { channel="rfxcom:rfy:0001:thing_rts_kitchen:shutter" }
    String state_auto_shutter_kitchen     "RTS Kitchen AUTO"    (mysql)
    String state_sunlit_shutter_kitchen   "RTS Kitchen SUNLIT"  (mysql)


## Enjoy ;-)
