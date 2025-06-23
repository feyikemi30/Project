import json
from elasticsearch import Elasticsearch

es = Elasticsearch(
    "https://your-es-url",  
    basic_auth=("your-username", "your-password"),  
    verify_certs=True
)

def main():
    indexing_timestamp = "2024-06-20T00:00:00Z"  

    # Load Server Compliance Data
    with open("files/server_compliance_reporting.json") as f:
        transformed_data = json.load(f)

    final_data = [record for record in transformed_data if record.get("appCode")]
    print(f"Final record count after filtering invalid appCodes: {len(final_data)}")

    # Pre-fetch IIPM enrichment data
    iipm_query = {
        "query": {
            "exists": {
                "field": "appCode"
            }
        },
        "_source": [
            "appCode",
            "name",
            "lineOfBusiness",
            "contactPerson",
            "contactType",
            "contactMechanism"
        ],
        "size": 10000
    }

    try:
        iipm_results = es.search(index="atu0-iipm-digital-data", body=iipm_query)
    except Exception as e:
        print(f"[ERROR] Failed to fetch IIPM data: {e}")
        return

    iipm_lookup = {
        hit["_source"]["appCode"]: hit["_source"]
        for hit in iipm_results["hits"]["hits"]
    }

    print(f"Fetched IIPM enrichment for {len(iipm_lookup)} appCodes")

    # Enrich and Update Server Compliance Index
    for i, appcode_detail in enumerate(final_data):
        appCode = appcode_detail.get("appCode")
        appcode_detail["timestamp"] = indexing_timestamp

        # Enrich from IIPM lookup
        if appCode in iipm_lookup:
            enrichment = iipm_lookup[appCode]
            for field in ["name", "lineOfBusiness", "contactPerson", "contactType", "contactMechanism"]:
                if enrichment.get(field):
                    appcode_detail[field] = enrichment[field]
            print(f"[ENRICHED] {appCode} with IIPM fields.")
        else:
            print(f"[SKIP] No IIPM data for {appCode}")

        # Search for existing server compliance records
        search_query = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"appCode.keyword": appCode}}
                    ],
                    "must_not": [
                        {"term": {"documentType.keyword": "application_metadata"}}
                    ]
                }
            }
        }

        try:
            response = es.search(index="atu0-server-compliance-metrics", body=search_query)
            existing_records = response.get("hits", {}).get("hits", [])

            if not existing_records:
                print(f"[NO MATCH] No server compliance record found for {appCode}")
            else:
                for record in existing_records:
                    record_id = record.get("_id")
                    updated_source = record.get("_source", {})
                    updated_source.update(appcode_detail)

                    es.update(
                        index="atu0-server-compliance-metrics",
                        id=record_id,
                        body={"doc": updated_source}
                    )
                    print(f"[UPDATED] Record {record_id} for {appCode}")

        except Exception as e:
            print(f"[ERROR] Failed to update {appCode}: {e}")

if __name__ == "__main__":
    main()
