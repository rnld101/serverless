import os
import boto3

ses = boto3.client("ses")

SENDER = os.getenv("SENDER", "arnoldrnld101@gmail.com")
RECIPIENT = os.getenv("RECIPIENT", "arnoldrnld101@gmail.com")


def lambda_handler(event, context):

    print("Received Stream Event")

    for record in event.get("Records", []):

        event_name = record.get("eventName")

        # Process only newly inserted orders
        if event_name != "INSERT":
            continue

        try:

            print(f"Event ID   : {record.get('eventID')}")
            print(f"Event Type : {event_name}")

            new_image = record["dynamodb"]["NewImage"]

            customer_id = new_image["customer_id"]["S"]
            order_id = new_image["order_id"]["S"]

            # Convert DynamoDB List to Python List
            items = [
                item["S"]
                for item in new_image.get("items", {}).get("L", [])
            ]

            items_text = ", ".join(items)

            # Handle both Number and String storage types
            amount = (
                new_image["amount"].get("N")
                or new_image["amount"].get("S")
            )

            print("🔔================== NEW ORDER ==================🔔")
            print(f"Customer ID : {customer_id}")
            print(f"Order ID    : {order_id}")
            print(f"Items       : {items_text}")
            print(f"Amount      : ${amount}")
            print("=================================================")

            try:

                response = ses.send_email(
                    Source=SENDER,
                    Destination={
                        "ToAddresses": [RECIPIENT]
                    },
                    Message={
                        "Subject": {
                            "Data": f"New Order Created - {order_id}"
                        },
                        "Body": {
                            "Text": {
                                "Data": f"""
New Order Created

Customer ID : {customer_id}
Order ID    : {order_id}

Items       : {items_text}
Amount      : ${amount}

Generated from DynamoDB Stream Event
"""
                            }
                        }
                    }
                )

                print("✅ Email sent successfully")
                print(
                    f"Message ID: {response.get('MessageId')}"
                )

            except Exception as e:

                print(
                    f"❌ SES Error: {str(e)}"
                )

        except Exception as e:

            print(
                f"❌ Record Processing Error: {str(e)}"
            )

    return {
        "statusCode": 200,
        "body": "Successfully processed stream records"
    }


# import json

# def lambda_handler(event, context):
#     print("Received Stream Event:", json.dumps(event))
    
#     # A single event can contain multiple records
#     for record in event.get('Records', []):
#         # We only care about new items being inserted
#         if record['eventName'] == 'INSERT':
#             # NEW_IMAGE contains the item attributes after the insertion
#             new_image = record['dynamodb']['NewImage']
            
#             # DynamoDB Stream data is typed (e.g., {'S': 'CUST-101'})
#             customer_id = new_image['customer_id']['S']
#             order_id = new_image['order_id']['S']
            
#             print(f"✅ [NOTIFICATION] New Order Placed !!! 🔔")
#             print(f"✅ Customer: {customer_id} | Order: {order_id}")
#             print("✅ Sending email to fulfillment center...")
            
#     return {"statusCode": 200, "body": "Successfully processed stream records"}