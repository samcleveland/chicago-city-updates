# active_businesses.py

import os
from datetime import datetime

from dotenv import load_dotenv

import pandas as pd
from sodapy import Socrata

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    select,
)

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker


class ActiveBusinesses:
    """
    Tracks Chicago business licenses.

    Sources:
        Active Businesses:
            uupf-x98q


        Business Closed:
            ytxg-j8ei

    Creates:
        business_license_snapshot
        business_closed_snapshot
        business_events
    """

    ACTIVE_DATASET_ID = "uupf-x98q"
    CLOSED_DATASET_ID = "ytxg-j8ei"
    DOMAIN = "data.cityofchicago.org"

    def __init__(self):
    
        load_dotenv()
    
        database_url = os.getenv("DATABASE_URL")
    
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
        )
    
        self.Session = sessionmaker(
            bind=self.engine
        )
    
        self.client = Socrata(
            self.DOMAIN,
            os.getenv("DP_TOKEN"),
        )
    
        self.metadata = MetaData()
    
        self.create_tables()

    def create_tables(self):
        self.active_snapshot = Table(
            "business_license_snapshot",
            self.metadata,
            Column("snapshot_date", Date),
            Column("business_key", String, index=True),
            Column("account_number", String),
            Column("site_number", String),
            Column("license_id", String),
            Column("business_name", String),
            Column("legal_name", String),
            Column("address", String),
            Column("latitude", Float),
            Column("longitude", Float),
            Column("license_type", String),
            Column("application_type", String),
            Column("expiration_date", Date),
            UniqueConstraint(
                "snapshot_date",
                "business_key",
                name="uq_business_snapshot_date_key",
            ),
        )

        self.closed_snapshot = Table(
            "business_closed_snapshot",
            self.metadata,
            Column("snapshot_date", Date),
            Column("business_key", String, index=True),
            Column("account_number", String),
            Column("site_number", String),
            Column("license_id", String),
            Column("business_name", String),
            Column("address", String),
            Column("latitude", Float),
            Column("longitude", Float),
            Column("license_status", String),
            Column("status_date", Date),
            UniqueConstraint(
                "snapshot_date",
                "business_key",
                name="uq_business_closed_date_key",
            ),
        )

        self.events = Table(
            "business_events",
            self.metadata,
            Column("event_type", String),
            Column("event_date", DateTime),
            Column("business_key", String),
            Column("business_name", String),
            Column("address", String),
            Column("latitude", Float),
            Column("longitude", Float),
            Column("confidence_score", Float),
            Column("reason", String),
            UniqueConstraint(
                "event_type",
                "business_key",
                "event_date",
                name="uq_business_event",
            ),
        )

        self.metadata.create_all(
            self.engine
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
                ).dt.date
    
        return df

    def extract_coordinates(self, df):
        if "location" not in df.columns:
            df["latitude"] = None
            df["longitude"] = None
            return df
    
        df["latitude"] = df["location"].apply(
            lambda x: x.get("latitude")
            if isinstance(x, dict)
            else None
        )
    
        df["longitude"] = df["location"].apply(
            lambda x: x.get("longitude")
            if isinstance(x, dict)
            else None
        )
    
        df = df.drop(
            columns=["location"]
        )
    
        return df

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
                "license_status_change_date": "status_date",
            }
        )
        
        #df = self.extract_coordinates(df)
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
    
        #df = self.extract_coordinates(df)
    
        df = self.clean_dates(df)
    
        return df

    def save_dataframe(self, df, table, chunk_size=500):
        if df.empty:
            return
    
        valid_columns = {
            column.name
            for column in table.columns
        }
    
        df = df[
            [
                col
                for col in df.columns
                if col in valid_columns
            ]
        ]
    
        # Debug date columns
        for col in [
            "snapshot_date",
            "expiration_date",
            "status_date",
        ]:
            if col in df.columns:
                print(f"\n{col}:")
                print(
                    df[col]
                    .apply(lambda x: type(x).__name__)
                    .value_counts()
                )
    
        records = df.to_dict("records")
    
        with self.engine.begin() as conn:
            for i in range(
                0,
                len(records),
                chunk_size,
            ):
                chunk = records[i:i + chunk_size]
    
                stmt = (
                    insert(table)
                    .values(chunk)
                    .on_conflict_do_nothing()
                )
                
                conn.execute(stmt)

    def get_previous_active_snapshot(self):
        query = (
            select(
                self.active_snapshot
            )
            .order_by(
                self.active_snapshot.c.snapshot_date.desc()
            )
        )

        df = pd.read_sql(
            query,
            self.engine,
        )

        if df.empty:
            return df

        latest_date = (
            df["snapshot_date"]
            .max()
        )

        return df[
            df["snapshot_date"]
            < latest_date
        ]

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
        )

        for _, row in current[
            ~current.business_key.isin(previous_keys)
        ].iterrows():

            events.append(
                {
                    "event_type": "NEW_BUSINESS",
                    "event_date": datetime.now(),
                    "business_key": row.business_key,
                    "business_name": row.business_name,
                    "address": row.address,
                    "latitude": row.latitude,
                    "longitude": row.longitude,
                    "confidence_score": 100,
                    "reason": (
                        "New active license detected"
                    ),
                }
            )

        for _, row in previous[
            ~previous.business_key.isin(current_keys)
        ].iterrows():

            confirmed = (
                row.business_key
                in closed_keys
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
                    "latitude": row.latitude,
                    "longitude": row.longitude,
                    "confidence_score": (
                        100
                        if confirmed
                        else 50
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

        previous = (
            self.get_previous_active_snapshot()
        )

        self.save_dataframe(
            active,
            self.active_snapshot,
        )

        self.save_dataframe(
            closed,
            self.closed_snapshot,
        )

        events = self.detect_events(
            active,
            previous,
            closed,
        )

        self.save_dataframe(
            pd.DataFrame(events),
            self.events,
        )
    

        return pd.DataFrame(events)


if __name__ == "__main__":
    tracker = ActiveBusinesses()

    events = tracker.run()

    if events.empty:
        print(
            "No business changes detected."
        )
    else:
        print(events)