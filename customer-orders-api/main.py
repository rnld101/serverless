import os
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from mangum import Mangum
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone

app = FastAPI(title="Customer Orders API")
handler = Mangum(app)

# Frontend connection
from fastapi.middleware.cors import CORSMiddleware

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production S3, change to your specific S3 bucket website URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Initialize boto3 DynamoDB resource
dynamodb = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION', 'us-east-1'))
TABLE_NAME = os.getenv('DYNAMODB_TABLE_NAME', 'OrdersDB')
table = dynamodb.Table(TABLE_NAME)

# --- Pydantic Models ---
class CreateOrderRequest(BaseModel):
    customer_id: str
    amount: float
    items: list[str]

class UpdateStatusRequest(BaseModel):
    status: str


# --- HTTP Methods ---

# 1. CREATE an order
@app.post("/orders")
def create_order(order: CreateOrderRequest):
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    # Python 3.13 fix: Use timezone-aware UTC as utcnow() is deprecated
    timestamp = datetime.now(timezone.utc).isoformat()
    
    item = {
        'customer_id': order.customer_id,
        'order_id': order_id,
        'amount': str(order.amount), # DynamoDB handles floats best as strings/Decimals
        'items': order.items,
        'status': 'PENDING',
        'created_at': timestamp
    }
    
    table.put_item(Item=item)
    return {"message": "Order created successfully", "order": item}

# 2. GET all orders for a specific customer
@app.get("/orders/customer/{customer_id}")
def get_customer_orders(customer_id: str):
    response = table.query(
        KeyConditionExpression=Key('customer_id').eq(customer_id)
    )
    return {"orders": response.get('Items', [])}

# 3. GET a specific order (Requires Full Primary Key)
@app.get("/orders/{customer_id}/{order_id}")
def get_order(customer_id: str, order_id: str):
    response = table.get_item(
        Key={
            'customer_id': customer_id,
            'order_id': order_id
        }
    )
    if 'Item' not in response:
        raise HTTPException(status_code=404, detail="Order not found")
        
    return response['Item']

# 4. NEW: GET ALL orders in the table (Scan Operation)
@app.get("/orders")
def get_all_orders():
    """
    Retrieves all orders using a DynamoDB Scan. 
    Note: For large production datasets, implement pagination using ExclusiveStartKey.
    """
    response = table.scan()
    return {"orders": response.get('Items', [])}


# 5. NEW: UPDATE order status
@app.patch("/orders/{customer_id}/{order_id}")
def update_order_status(customer_id: str, order_id: str, body: UpdateStatusRequest):
    try:
        response = table.update_item(
            Key={
                'customer_id': customer_id,
                'order_id': order_id
            },
            UpdateExpression="set #s = :status_val",
            ExpressionAttributeNames={
                '#s': 'status' # 'status' is a DynamoDB reserved keyword, so we use an alias
            },
            ExpressionAttributeValues={
                ':status_val': body.status.upper()
            },
            ReturnValues="UPDATED_NEW"
        )
        return {"message": "Order updated successfully", "updated_attributes": response.get("Attributes")}
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        raise HTTPException(status_code=404, detail="Order not found")


# 6. NEW: DELETE an order
@app.delete("/orders/{customer_id}/{order_id}")
def delete_order(customer_id: str, order_id: str):
    # Check if item exists first to return a proper 404 if missing
    existing = table.get_item(Key={'customer_id': customer_id, 'order_id': order_id})
    if 'Item' not in existing:
        raise HTTPException(status_code=404, detail="Order not found")

    table.delete_item(
        Key={
            'customer_id': customer_id,
            'order_id': order_id
        }
    )
    return {"message": f"Order {order_id} deleted successfully"}