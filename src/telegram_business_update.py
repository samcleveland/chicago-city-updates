# telegram_business_update.py

import os
from pathlib import Path
from dotenv import load_dotenv

import pandas as pd
import requests

import numpy as np

import json

from datetime import date, timedelta


class ActiveBusinessesLoader:
    """
    Loads the active business parquet file.
    """

    def __init__(self, parquet_path: str = "data/active_businesses.parquet"):
        self.parquet_path = Path(parquet_path)

    def load(self) -> pd.DataFrame:
        if not self.parquet_path.exists():
            raise FileNotFoundError(
                f"Parquet file not found: {self.parquet_path}"
            )

        cutoff = pd.Timestamp(date.today() - timedelta(days=1))

        active_businesses = pd.read_parquet(self.parquet_path)

        active_businesses["date_issued"] = pd.to_datetime(
                                            active_businesses["date_issued"],
                                            errors="coerce"
)

        return active_businesses[(active_businesses["application_type"] == 'ISSUE') &
                                              (active_businesses['date_issued'] >= cutoff)]

    def filter_table_for_near(self, df, local_lon, local_lat, distance=1):
        
        R = 3958.8  # Earth radius in miles

        lat1 = np.radians(local_lat)
        lon1 = np.radians(local_lon)
        
        lat2 = np.radians(df["latitude"].astype(float))
        lon2 = np.radians(df["longitude"].astype(float))
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = (
            np.sin(dlat / 2) ** 2
            + np.cos(lat1)
            * np.cos(lat2)
            * np.sin(dlon / 2) ** 2
        )
        
        df["distance"] = 2 * R * np.arcsin(np.sqrt(a))
        
        return df[df["distance"] <= distance].sort_values('distance')


class TelegramNotifier:
    """
    Sends messages to Telegram.
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send_message(self, text: str) -> None:
        url = (
            f"https://api.telegram.org/bot"
            f"{self.bot_token}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=30,
        )

        response.raise_for_status()


class BusinessUpdateProcessor:
    """
    Loads active businesses and sends a summary message.
    """

    def __init__(
        self,
        parquet_path: str,
        telegram_token: str,
        telegram_chat_id: str,
    ):
        self.loader = ActiveBusinessesLoader(parquet_path)

        self.telegram = TelegramNotifier(
            bot_token=telegram_token,
            chat_id=telegram_chat_id,
        )

    def run(self, user_lat, user_lon, distance) -> None:
        df = self.loader.load()

        df = self.loader.filter_table_for_near(df, local_lat=user_lat, local_lon=user_lon, distance=distance)

        for index, row in df.iterrows():

            message = (
                f"Business Name: {row.business_name}\n"
                f"Address: {row.address}\n"
                f"License Type: {row.license_type }\n"
                f"Distance: {row.distance}"
            )

            self.telegram.send_message(message)

        print("Telegram message sent successfully.")


def main() -> None:
    load_dotenv()

    users = json.loads(os.environ['LOCATIONS'])

    for user_values in users.values():

        processor = BusinessUpdateProcessor(
            parquet_path="data/active_businesses.parquet",
            telegram_token=os.environ["TELEGRAM_TOKEN"],
            telegram_chat_id=user_values['CHAT_ID'],
         )

        processor.run(
                user_lat=float(user_values["LATITUDE"]),
                user_lon=float(user_values['LONGITUDE']),
                distance=float(user_values["DISTANCE"])
         )


if __name__ == "__main__":
    main()
