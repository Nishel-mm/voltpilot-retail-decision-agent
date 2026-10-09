from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    today: str
    database: str


class Assumption(BaseModel):
    key: str
    value: str
    description: str
    source: str


class DecisionAction(BaseModel):
    note: str = Field(default="", max_length=500)
    option_id: str | None = None


class SupplierDeliveryUpdate(BaseModel):
    """Delivery update submitted through the local simulated supplier portal."""
    supplier_contact: str = Field(min_length=2, max_length=100)
    status: Literal["confirmed", "delayed", "in_transit"]
    revised_expected_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str = Field(min_length=5, max_length=600)


class StoreSaleItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)


class StoreCheckout(BaseModel):
    store_id: int = Field(gt=0)
    customer_name: str = Field(default="", max_length=100)
    payment_method: Literal["cash", "upi", "card"] = "upi"
    items: list[StoreSaleItem] = Field(min_length=1, max_length=50)


class StoreProductCreate(BaseModel):
    """Create a catalog SKU and record its opening stock at one store."""
    store_id: int = Field(gt=0)
    sku: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=140)
    category: str = Field(min_length=2, max_length=60)
    unit_cost: float = Field(ge=0, le=100000000)
    selling_price: float = Field(gt=0, le=100000000)
    initial_stock: int = Field(default=0, ge=0, le=100000)
    note: str = Field(default="Added from Store & Product Vault", max_length=400)


class InventoryStockReceipt(BaseModel):
    """Record received units of an existing SKU at a selected store."""
    store_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)
    note: str = Field(default="Stock received at store", max_length=400)


class StoreCreate(BaseModel):
    """Create a real store/location in the retailer's workspace."""
    code: str = Field(min_length=2, max_length=12, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=140)
    city: str = Field(min_length=2, max_length=80)
    region: str = Field(min_length=2, max_length=80)
