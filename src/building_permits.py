# -*- coding: utf-8 -*-


import os

import pandas as pd
import numpy as np


from sodapy import Socrata
from dotenv import load_dotenv

from datetime import date, timedelta

from math import radians, sin, cos, sqrt, atan2


class BuildingPermits():
    def __init__(self):
        load_dotenv()
        
        self.domain = "data.cityofchicago.org"
        self.app_token = os.getenv("DP_TOKEN")
        
        self.client = Socrata(
            self.domain,
            self.app_token,
        )
        

    def load_building_permits(self):
        yesterday = date.today() - timedelta(days=7)

        yesterday_string = f"'{yesterday.year}-{yesterday.month}-{yesterday.day}T00:00:00'"

        results = self.client.get(
            "ydr8-5enu",
            where=f"application_start_date >= {yesterday_string}",
            limit=20000
        )
    
        df = pd.DataFrame.from_records(results)
    
        # Initialize derived columns
        df["contact_owner"] = pd.NA
        df["contact_owner_type"] = pd.NA
    
        for i in range(1, 14):
            type_col = f"contact_{i}_type"
            name_col = f"contact_{i}_name"
    
            if type_col not in df.columns or name_col not in df.columns:
                continue
    
            owner_mask = (
                df[type_col]
                .str.contains("owner", case=False, na=False)
                & df["contact_owner"].isna()
            )
    
            df.loc[owner_mask, "contact_owner"] = df.loc[owner_mask, name_col]
            df.loc[owner_mask, "contact_owner_type"] = df.loc[owner_mask, type_col]
    
        return df
    
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
        
        return df[df["distance"] <= distance]
                

if __name__ == "__main__":
    BP = BuildingPermits()

    results = BP.load_building_permits()
    close_results = BP.filter_table_for_near(results, -87.6486287, 41.9314542).sort_values('distance', ascending=True)

    print(close_results.to_json(orient='records', indent=4))



