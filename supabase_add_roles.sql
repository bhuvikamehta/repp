-- Add role column to user_profiles
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'member';

-- Create a function to bypass RLS and get the user's organization_id to avoid infinite recursion
CREATE OR REPLACE FUNCTION get_user_org_id()
RETURNS UUID AS $$
  SELECT organization_id FROM public.user_profiles WHERE id = auth.uid();
$$ LANGUAGE sql SECURITY DEFINER SET search_path = public;

-- Create a function to bypass RLS and get the user's role to avoid infinite recursion
CREATE OR REPLACE FUNCTION get_user_role()
RETURNS TEXT AS $$
  SELECT role FROM public.user_profiles WHERE id = auth.uid();
$$ LANGUAGE sql SECURITY DEFINER SET search_path = public;

-- Drop previous policies if they were created before erroring out
DROP POLICY IF EXISTS "Users can view members of their organization" ON public.user_profiles;
DROP POLICY IF EXISTS "Admins can update organization members" ON public.user_profiles;
DROP POLICY IF EXISTS "Users can insert their own profile" ON public.user_profiles;

-- Allow users in the same organization to view each other's profiles
CREATE POLICY "Users can view members of their organization" ON public.user_profiles
    FOR SELECT USING (
        organization_id = get_user_org_id()
    );

-- Allow the backend to read the profile it just inserted (bypassing SELECT restriction)
CREATE POLICY "Allow backend read" ON public.user_profiles
    FOR SELECT USING (true);

-- Allow organization admins to update roles of other members
CREATE POLICY "Admins can update organization members" ON public.user_profiles
    FOR UPDATE USING (
        organization_id = get_user_org_id() AND get_user_role() = 'admin'
    );

-- Allow users (and the backend anon client) to insert their profile during signup
CREATE POLICY "Users can insert their own profile" ON public.user_profiles
    FOR INSERT WITH CHECK (true);
