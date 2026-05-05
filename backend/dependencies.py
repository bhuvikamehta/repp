from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from routers.auth import supabase

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    try:
        user_res = supabase.auth.get_user(credentials.credentials)
        if not user_res.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_res.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
