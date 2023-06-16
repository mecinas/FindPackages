import json
import requests
import calendar
import logging
import azure.functions as func
import datetime
import os
from tgtg import TgtgClient


# def findTelegramId():
#     bot_token = "<telegram-bot-token>"
#     send_text = 'https://api.telegram.org/bot' + bot_token + '/getUpdates'
#     response = json.loads(requests.get(send_text))
#     id = response["result"]["chat"]["id"]
#     return id

# def tgtgGetToken():
#     client = TgtgClient(email="<email-here>")
#     credentials = client.get_credentials()
#     return credentials

TIME_MARGIN = datetime.datetime.now() - datetime.timedelta(minutes=9)

def send_notification(bot_message, bot_token):
    send_text = 'https://api.telegram.org/bot' + bot_token + '/sendMessage?chat_id=' + os.getenv("TELEGRAM_CHAT_ID") + '&parse_mode=Markdown&text=' + bot_message
    response = requests.get(send_text)
    return response.json()

def createMessage(name, meals_left, address, day, open, close):
    message = "Package is available in: " + name + "\nThere are left " + meals_left + " meals\n" + "The address of package is:\n" + address + \
        "\nPackage can be picked up at " + day +" from " + open + " to " + close + "\n\n"
    return message

def foodsiCreateMessage(restaurant):
    day_of_week = list(calendar.day_name)[restaurant["package_day"]["collection_day"]["week_day"]]
    close_time = restaurant["package_day"]["collection_day"]["closed_at"][11:16]
    open_time = restaurant["package_day"]["collection_day"]["opened_at"][11:16]
    return createMessage(restaurant["name"], str(restaurant["package_day"]["meals_left"]), restaurant["address"], day_of_week, close_time, open_time)

def foodsiAuthRequest():
    auth_data = {
        "email": os.getenv("FOODSI_EMAIL"),
        "password": os.getenv("FOODSI_PASSWORD")
    }
    headers = {'Content-type': 'application/json',
            'system-version': 'android_3.0.0', 'user-agent': 'okhttp/3.12.0'}
    url = "https://api.foodsi.pl/api/v2/auth/sign_in"
    foodsi_api = requests.post(url, headers=headers, data=json.dumps(auth_data))
    return foodsi_api

def foodsiMakeGetRequest(auth_headers):
    req_json = {
        "page": 1,
        "per_page": 100,
        "distance": {
            "lat": 52.21414461551087, 
            "lng": 21.036202678072446,
            "range": 7000
        },
        "hide_unavailable": True,
        "food_type": [],
        "collection_time": {
            "from": "00:00:00",
            "to": "23:59:59"
        }
    }
    url = "https://api.foodsi.pl/api/v2/restaurants"
    foodsi_api = requests.get(
        url, headers=auth_headers, data=json.dumps(req_json))
    content = json.loads(foodsi_api.content)
    return content

def getfoodsiPackages(foodsiInputblob: str, foodsiOutputblob: func.Out[str]):
    foodsi_login_api = foodsiAuthRequest()
    content = foodsiMakeGetRequest(foodsi_login_api.headers)

    foodsi_login_response = json.loads(foodsi_login_api.content)
    fav_id_list = foodsi_login_response["data"]["favourite_restaurants"]
    frequent_packages = json.loads(foodsiInputblob)
    message = ""

    for restaurant in content["data"]:
        if (restaurant["package_id"] in fav_id_list):
            notification_status = checkIfAlreadyNotified(frequent_packages, restaurant["name"])
            frequent_packages = notification_status["frequent_packages"]
            if not notification_status["should_notify"]:
                continue
            message += foodsiCreateMessage(restaurant)
    foodsiOutputblob.set(json.dumps(frequent_packages))
    message = message[:-2]
    return message

def tgtgCreateMessage(restaurant):
    day = restaurant["pickup_interval"]["start"][5:10]
    close_time = restaurant["pickup_interval"]["end"][11:16]
    open_time = restaurant["pickup_interval"]["start"][11:16]
    return createMessage(restaurant["display_name"], str(restaurant["items_available"]), restaurant["pickup_location"]["address"]["address_line"], day, close_time, open_time)

def checkIfAlreadyNotified(frequent_packages, package_name):
    format = "%d/%m/%Y, %H:%M:%S"
    notification_status = {"should_notify": True}
    
    if package_name in frequent_packages.keys():
        time_of_last_package_availbility = datetime.datetime.strptime(frequent_packages[package_name], format)
        if time_of_last_package_availbility > TIME_MARGIN:
            notification_status["should_notify"] = False
    frequent_packages[package_name] = datetime.datetime.now().strftime(format)

    notification_status["frequent_packages"] = frequent_packages
    return notification_status

def tgtgPackages(tgtgInputblob: str, tgtgOutputblob: func.Out[str]):
    client = TgtgClient(access_token=os.getenv("TGTG_ACCESS_TOKEN"), refresh_token=os.getenv("TGTG_REFRESH_TOKEN"), user_id=os.getenv("TGTG_USER_ID"), cookie=os.getenv("TGTG_COOKIE"))
    frequent_packages = json.loads(tgtgInputblob)
    message = ""
    for restaurant in client.get_items(with_stock_only=True):
        notification_status = checkIfAlreadyNotified(frequent_packages, restaurant["display_name"])
        frequent_packages = notification_status["frequent_packages"]
        if not notification_status["should_notify"]:
            continue
        message += tgtgCreateMessage(restaurant)
    message = message[:-2]
    tgtgOutputblob.set(json.dumps(frequent_packages))
    return message

def main(mytimer: func.TimerRequest, foodsiInputblob: str, foodsiOutputblob: func.Out[str], tgtgInputblob: str, tgtgOutputblob: func.Out[str]):
    tgtg_message = tgtgPackages(tgtgInputblob, tgtgOutputblob)
    logging.info(tgtg_message)
    response = send_notification(tgtg_message, os.getenv("TGTG_BOT_TOKEN"))

    foodsi_message = getfoodsiPackages(foodsiInputblob, foodsiOutputblob)
    logging.info(foodsi_message)
    response = send_notification(foodsi_message, os.getenv("FOODSI_BOT_TOKEN"))

#Dopisać sprawdzenie w blob czy paczka była niedawno wykryta

