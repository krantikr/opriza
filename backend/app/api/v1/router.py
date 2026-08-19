"""Aggregates the v1 routers.

Order matters: a literal path must be registered before a parameterised one it
would otherwise be swallowed by. `ops` owns `/stock/holds`, while `catalog`
owns `/stock/{stock_item_id}` - registered the other way round, "holds" is read
as an id and the request 422s.
"""

from fastapi import APIRouter

from app.api.v1 import catalog, dashboard, emails, ops, pipeline, pricing, quotations

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(emails.router)
api_router.include_router(quotations.router)
api_router.include_router(pricing.router)
api_router.include_router(ops.router)
api_router.include_router(catalog.router)
api_router.include_router(dashboard.router)
api_router.include_router(pipeline.router)
