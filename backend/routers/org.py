from fastapi import APIRouter, HTTPException, Depends
from schemas import UpdateRoleRequest
from typing import List, Dict, Any
from .auth import supabase
from dependencies import get_current_user

router = APIRouter(prefix="/org", tags=["org"])

async def get_current_admin(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
    
    # Get user profile to check role
    profile_res = supabase.table('user_profiles').select('*').eq('id', user_id).execute()
    if not profile_res.data:
        raise HTTPException(status_code=404, detail="User profile not found")
        
    profile = profile_res.data[0]
    if profile.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
        
    return profile

@router.get("/members")
async def get_members(user_id: str = Depends(get_current_user)):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
        
    # First get the user's organization and role
    profile_res = supabase.table('user_profiles').select('organization_id, role').eq('id', user_id).execute()
    if not profile_res.data or not profile_res.data[0].get('organization_id'):
        raise HTTPException(status_code=400, detail="User does not belong to an organization")
        
    org_id = profile_res.data[0]['organization_id']
    is_admin = profile_res.data[0].get('role') == 'admin'
    
    # Get organization info
    org_res = supabase.table('organizations').select('name, code').eq('id', org_id).execute()
    org_info = org_res.data[0] if org_res.data else None
    
    # Only return members if the user is an admin
    if is_admin:
        members_res = supabase.table('user_profiles').select('id, email, role, created_at').eq('organization_id', org_id).execute()
        members_data = members_res.data
    else:
        members_data = []
        
    return {"members": members_data, "organization": org_info}

@router.put("/members/{member_id}/role")
async def update_member_role(member_id: str, req: UpdateRoleRequest, admin_profile: Dict[str, Any] = Depends(get_current_admin)):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
        
    org_id = admin_profile['organization_id']
    
    # Verify the target member belongs to the same organization
    member_res = supabase.table('user_profiles').select('organization_id').eq('id', member_id).execute()
    if not member_res.data or member_res.data[0].get('organization_id') != org_id:
        raise HTTPException(status_code=404, detail="Member not found in your organization")
        
    # Update role
    try:
        updated = supabase.table('user_profiles').update({"role": req.role}).eq('id', member_id).execute()
        return {"message": "Role updated successfully", "member": updated.data[0]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/members/{member_id}")
async def remove_member(member_id: str, admin_profile: Dict[str, Any] = Depends(get_current_admin)):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase not configured")
        
    org_id = admin_profile['organization_id']
    
    # Prevent admin from removing themselves (optional, but good practice)
    if member_id == admin_profile['id']:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
        
    # Verify the target member belongs to the same organization
    member_res = supabase.table('user_profiles').select('organization_id').eq('id', member_id).execute()
    if not member_res.data or member_res.data[0].get('organization_id') != org_id:
        raise HTTPException(status_code=404, detail="Member not found in your organization")
        
    # Remove member from organization (unlink)
    try:
        supabase.table('user_profiles').update({"organization_id": None, "role": "member"}).eq('id', member_id).execute()
        return {"message": "Member removed from organization successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
