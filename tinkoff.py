import argparse
import hashlib
import json
import logging
import requests
import time

from haversine import haversine
from jinja2 import Environment, FileSystemLoader


class TinkoffClient():
    def __init__(self):
        pass
    
    def atms(
        self,
        currencies,
        bounds
    ):
        request_body = {
             "bounds": {
                "bottomLeft": {"lat": bounds[0][0], "lng": bounds[0][1]},
                "topRight": {"lat": bounds[1][0], "lng": bounds[1][1]}
            },
            "filters": {
                "showUnavailable": True, 
                "currencies": currencies
            },
            "zoom": 12
        }
        request = requests.post('https://api.tinkoff.ru/geo/withdraw/clusters', json=request_body)
        request.raise_for_status()

        atms = []
        for cluster in request.json()["payload"]["clusters"]:
            for point in cluster["points"]:
                atm = {
                    "id": point["id"],
                    "address": point["address"],
                    "location": (point["location"]["lat"], point["location"]["lng"]),
                    "available": point["atmInfo"]["available"],
                    "limits": []
                }
                for limit in point["limits"]:
                    if limit["currency"] not in currencies:
                        continue
                    atm["limits"].append({"currency": limit["currency"], "amount": limit["amount"]})
                atms.append(atm)
        
        return atms
    
    
class TelegramClient:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id

    def post(self, url, params):
        try:
            return requests.post(url, data=params)
        except Exception:
            time.sleep(10)
            return self.post(url, params)
    
    def send_text(self, text):
        url_template = "https://api.telegram.org/bot{}/sendMessage"
        params = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "html",
            "disable_web_page_preview": True,
            "disable_notification": True
        }
        return self.post(url_template.format(self.token), params)

    
def main(token, log_level, template_path, config_path):
    logging.basicConfig(format="%(asctime)s - %(message)s", level=log_level)
    
    jinja_env = Environment(loader=FileSystemLoader("."))
    template = jinja_env.get_template(template_path)
    
    with open(config_path, "r") as f:
        config = json.load(f)

    tinkoff_client = TinkoffClient()
    telegram_client = TelegramClient(token, config["chat_id"])
    
    bounds = (config["bounds"]["bottom_left"], config["bounds"]["top_right"])
    
    def add_poi_distances(pois, atms):
        for atm in atms:
            _pois = [{"name": p["name"], "distance": haversine(atm["location"], p["location"])} for p in pois]
            atm.update({"pois": sorted(_pois, key=lambda p: p["distance"])})

    sent_text_hash = None
    while True:
        if atms := tinkoff_client.atms(config["currencies"], bounds):
            logging.info("{} ATMs".format(len(atms)))

            add_poi_distances(config["pois"], atms)
            atms.sort(key=lambda a: (-a["limits"][0]["amount"], a["pois"][0]["distance"]))

            text = template.render(atms=atms)
            text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
            if text_hash != sent_text_hash:
                telegram_client.send_text(text)
                sent_text_hash = text_hash
                logging.info("Message sent to {}".format(config["chat_id"]))
            else:
                logging.info("Message omitted - nothing new")
        else:
            logging.info("No ATMs")    
        time.sleep(config["sleep_time"])    


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", type=str, required=True)
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--template-path", type=str, default="message.html")
    parser.add_argument("--config-path", type=str, default="config.json")
    args = parser.parse_args()
    main(**vars(args))  