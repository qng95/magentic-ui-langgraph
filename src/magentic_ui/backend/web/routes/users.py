from fastapi import APIRouter, Depends, HTTPException

from ...datamodel import User
from ..deps import get_db

router = APIRouter()


@router.get("/")
async def list_users(db=Depends(get_db)):
    """List all users."""
    response = db.get(User)
    return {"status": response.status, "data": response.data}


@router.get("/{user_id}")
async def get_user(user_id: str, db=Depends(get_db)):
    response = db.get(User, filters={"id": user_id})
    if not response.status or not response.data:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": True, "data": response.data[0]}


@router.post("/")
async def create_or_update_user(user: User, db=Depends(get_db)):
    response = db.upsert(user)
    if not response.status:
        raise HTTPException(status_code=400, detail=response.message)
    return {"status": True, "data": response.data}
