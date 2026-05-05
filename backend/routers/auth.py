from fastapi import APIRouter, HTTPException, Depends
from schemas import OrganizationCreateRequest, SignupRequest, LoginRequest
import uuid
import os
from supabase import create_client, Client

router = APIRouter(prefix="/auth", tags=["auth"])

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key) if url and key else None

@router.post("/create-organization")
async def create_organization(req: OrganizationCreateRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    
    code = uuid.uuid4().hex[:8].upper()
    try:
        # Sign up in Supabase Auth
        auth_res = supabase.auth.sign_up({
            "email": req.email,
            "password": req.password
        })
        
        if not auth_res.user:
            raise HTTPException(status_code=400, detail="Signup failed")
            
        if not auth_res.user.identities:
            raise HTTPException(status_code=400, detail="User already exists")
            
        user_id = auth_res.user.id

        # Create organization
        response = supabase.table('organizations').insert({
            "name": req.name,
            "code": code
        }).execute()
        org_id = response.data[0]['id']
        
        # Create user profile as admin
        supabase.table('user_profiles').insert({
            "id": user_id,
            "email": req.email,
            "organization_id": org_id,
            "role": "admin"
        }).execute()
        
        return {"organization": response.data[0], "user": auth_res.user}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/signup")
async def signup(req: SignupRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    
    try:
        # Validate organization code
        org_res = supabase.table('organizations').select('id').eq('code', req.org_code).execute()
        if not org_res.data:
            raise HTTPException(status_code=400, detail="Invalid organization code")
        org_id = org_res.data[0]['id']
        
        # Sign up in Supabase Auth
        auth_res = supabase.auth.sign_up({
            "email": req.email,
            "password": req.password
        })
        
        if not auth_res.user:
            raise HTTPException(status_code=400, detail="Signup failed")
            
        if not auth_res.user.identities:
            raise HTTPException(status_code=400, detail="User already exists")
            
        user_id = auth_res.user.id
        
        # Create user profile mapped to the organization
        supabase.table('user_profiles').insert({
            "id": user_id,
            "email": req.email,
            "organization_id": org_id,
            "role": "member"
        }).execute()
        
        return {"message": "Signup successful", "user": auth_res.user}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/login")
async def login(req: LoginRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
        
    try:
        auth_res = supabase.auth.sign_in_with_password({
            "email": req.email,
            "password": req.password
        })
        return {"session": auth_res.session}
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")
