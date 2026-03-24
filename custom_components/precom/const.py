"""Constanten voor de Pre-Com integratie."""

DOMAIN = "precom"

# API
BASE_URL  = "https://app.pre-com.nl"
TOKEN_URL = f"{BASE_URL}/Token"
API_V1    = f"{BASE_URL}/api"
API_V2    = f"{BASE_URL}/api/v2"

# Configuratie sleutels
CONF_USERNAME            = "username"
CONF_PASSWORD            = "password"
CONF_SCAN_INTERVAL       = "scan_interval"
CONF_ALARM_SCAN_INTERVAL = "alarm_scan_interval"
CONF_SCHEDULE_SCAN_INTERVAL = "schedule_scan_interval"

# Standaardwaarden
DEFAULT_SCAN_INTERVAL       = 15   # 15 seconden voor rooster/userinfo
DEFAULT_ALARM_SCAN_INTERVAL = 30   # 30 seconden voor alarmcheckDEFAULT_SCHEDULE_SCAN_INTERVAL = 300  # 5 minuten voor rooster
# Events
EVENT_ALARM_RECEIVED = f"{DOMAIN}_alarm_received"

# Coordinator data keys
DATA_USER_INFO             = "user_info"
DATA_ALARM_MESSAGES        = "alarm_messages"
DATA_SCHEDULE              = "schedule"
DATA_AVAILABILITY_OVERRIDE = "availability_override"
