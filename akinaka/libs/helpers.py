from datetime import timedelta, timezone, datetime
import slack_sdk
import messagebird
import os
import logging

def datetime_this_seconds_ago(duration):
    """
    Take a duration in seconds and work out the datetime value for the datetime
    at that date and time ago
    """

    return (datetime.now(timezone.utc) + timedelta(seconds=-duration))

def seconds_from_hours(hours):
    return (60*60)*hours

def log(message):
    print(message)

def set_logger(level='INFO'):
    return logging.basicConfig(level=level, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S%z')

def send_sms(message):
    """ Send an SMS using our SMS provider """

    logging.info(f"Attempting to send SMS with message: {message}")

    try:
        MESSAGEBIRD_TOKEN = os.environ['MESSAGEBIRD_TOKEN']
        ONCALL_PHONE_NUMBERS = os.environ['ONCALL_PHONE_NUMBERS']
    except KeyError as e :
        logging.warning(f"{e} environment variable is not set. SMS alerts will not work")

    m_client = messagebird.Client(MESSAGEBIRD_TOKEN)
    m_client.message_create(originator='OpsCritical', body=message, recipients=ONCALL_PHONE_NUMBERS)

def alert(message):
    """ Send an alert to Slack """

    logging.info(f"Attempting to send Slack post with message: {message}")

    try:
        SLACK_BOT_TOKEN = os.environ['SLACK_BOT_TOKEN']
        DEPLOYMENT_ENVIRONMENT = os.environ['DEPLOYMENT_ENVIRONMENT']
    except KeyError as e:
        logging.warning(f"{e} environment variable is not set. Slack alerts will not work")
        send_sms(message)

    try:
        client = slack_sdk.WebClient(token=SLACK_BOT_TOKEN)
        response = client.chat_postMessage(channel=f"#monitoring-{DEPLOYMENT_ENVIRONMENT}", text=message)
        assert response["message"]["text"] == message
    except Exception as e:
        logging.error(f"Couldn't send alert: {e}")
        send_sms(message)
