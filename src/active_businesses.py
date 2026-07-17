import os
from datetime import datetime

from dotenv import load_dotenv
import pandas as pd
from sodapy import Socrata


class ActiveBusinesses:
    """
    Tracks Chicago business licenses.

    Sources:
        Active Businesses:
            uupf-x98q

        Business Closed:
            ytxg-j8ei

    Files:
        data/active_businesses.parquet
        data/closed_businesses.parquet
        data/business_events.parquet
    """

    ACTIVE_DATASET_ID = "uupf-x98q"
    CLOSED_DATASET_ID = "ytxg-j8ei"
    DOMAIN = "data.cityofchicago.org"

    def __init__(self):

        load_dotenv()

        self.client = Socrata(
            self.DOMAIN,
            os.getenv("DP_TOKEN"),
        )

        self.data_dir = "data"

        os.makedirs(
            self.data_dir,
            exist_ok=True,
        )

        self.active_snapshot_file = os.path.join(
            self.data_dir,
            "active_businesses.parquet",
        )

        self.closed_snapshot_file = os.path.join(
            self.data_dir,
            "closed_businesses.parquet",
        )

        self.events_file = os.path.join(
            self.data_dir,
            "business_events.parquet",
        )

    def clean_dates(self, df):

        date_columns = [
            "snapshot_date",
            "expiration_date",
            "status_date",
        ]

        for col in date_columns:

            if col in df.columns:

                df[col] = pd.to_datetime(
                    df[col],
                    errors="coerce",
                )

        return df

    def load_parquet(self, file_path):

        if not os.path.exists(file_path):
            return pd.DataFrame()

        return pd.read_parquet(file_path)

    def save_snapshot(
        self,
        df,
        file_path,
    ):

        if df.empty:
            return

        df.to_parquet(
            file_path,
            index=False,
        )

    def append_events(
        self,
        events_df,
    ):

        if events_df.empty:
            return

        existing = self.load_parquet(
            self.events_file
        )

        if existing.empty:
            combined = events_df.copy()
        else:
            combined = pd.concat(
                [existing, events_df],
                ignore_index=True,
            )

        combined = combined.drop_duplicates(
            subset=[
                "event_type",
                "business_key",
                "event_date",
            ]
        )

        combined.to_parquet(
            self.events_file,
            index=False,
        )

    def get_previous_active_snapshot(self):

        return self.load_parquet(
            self.active_snapshot_file
        )

    def download_active_businesses(self):

        query = """
            SELECT
                license_id,
                account_number,
                site_number,
                doing_business_as_name,
                legal_name,
                address,
                license_description,
                application_type,
                expiration_date,
                latitude,
                longitude
            LIMIT 500000
        """

        results = self.client.get(
            self.ACTIVE_DATASET_ID,
            query=query,
        )

        df = pd.DataFrame(results)

        if df.empty:
            raise ValueError(
                "No active business data returned"
            )

        df.columns = [
            c.lower()
            for c in df.columns
        ]

        df["business_key"] = (
            df["account_number"].astype(str)
            + "-"
            + df["site_number"].astype(str)
        )

        df["snapshot_date"] = (
            datetime.today().date()
        )

        df = df.rename(
            columns={
                "doing_business_as_name": "business_name",
                "license_description": "license_type",
            }
        )

        df = self.clean_dates(df)

        return df

    def download_closed_businesses(self):

        query = """
            SELECT
                license_id,
                account_number,
                site_number,
                doing_business_as_name,
                address,
                license_status,
                license_status_change_date,
                latitude,
                longitude
            LIMIT 500000
        """

        results = self.client.get(
            self.CLOSED_DATASET_ID,
            query=query,
        )

        df = pd.DataFrame(results)

        if df.empty:
            return df

        df.columns = [
            c.lower()
            for c in df.columns
        ]

        df["business_key"] = (
            df["account_number"].astype(str)
            + "-"
            + df["site_number"].astype(str)
        )

        df["snapshot_date"] = (
            datetime.today().date()
        )

        df = df.rename(
            columns={
                "doing_business_as_name": "business_name",
                "license_status_change_date": "status_date",
            }
        )

        df = self.clean_dates(df)

        return df

    def detect_events(
        self,
        current,
        previous,
        closed,
    ):

        if previous.empty:
            return []

        events = []

        current_keys = set(
            current["business_key"]
        )

        previous_keys = set(
            previous["business_key"]
        )

        closed_keys = set(
            closed["business_key"]
        ) if not closed.empty else set()

        new_businesses = current[
            ~current.business_key.isin(previous_keys)
        ]

        for _, row in new_businesses.iterrows():

            events.append(
                {
                    "event_type": "NEW_BUSINESS",
                    "event_date": datetime.now(),
                    "business_key": row.business_key,
                    "business_name": row.business_name,
                    "address": row.address,
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    "confidence_score": 100,
                    "reason": "New active license detected",
                }
            )

        removed_businesses = previous[
            ~previous.business_key.isin(current_keys)
        ]

        for _, row in removed_businesses.iterrows():

            confirmed = (
                row.business_key in closed_keys
            )

            events.append(
                {
                    "event_type": (
                        "CONFIRMED_CLOSURE"
                        if confirmed
                        else "POTENTIAL_CLOSURE"
                    ),
                    "event_date": datetime.now(),
                    "business_key": row.business_key,
                    "business_name": row.business_name,
                    "address": row.address,
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    "confidence_score": (
                        100 if confirmed else 50
                    ),
                    "reason": (
                        "Present in BusinessClosed dataset"
                        if confirmed
                        else "Removed from active licenses"
                    ),
                }
            )

        return events

    def run(self):

        print(
            "Downloading active businesses..."
        )

        active = (
            self.download_active_businesses()
        )

        print(
            "Downloading closed businesses..."
        )

        closed = (
            self.download_closed_businesses()
        )

        print(
            "Loading previous snapshot..."
        )

        previous = (
            self.get_previous_active_snapshot()
        )

        print(
            "Detecting events..."
        )

        events = self.detect_events(
            active,
            previous,
            closed,
        )

        events_df = pd.DataFrame(events)

        print(
            "Saving active snapshot..."
        )

        self.save_snapshot(
            active,
            self.active_snapshot_file,
        )

        print(
            "Saving closed snapshot..."
        )

        self.save_snapshot(
            closed,
            self.closed_snapshot_file,
        )

        print(
            "Saving events..."
        )

        self.append_events(
            events_df,
        )

        return events_df


if __name__ == "__main__":

    tracker = ActiveBusinesses()

    events = tracker.run()

    if events.empty:

        print(
            "No business changes detected."
        )

    else:

        print(events)