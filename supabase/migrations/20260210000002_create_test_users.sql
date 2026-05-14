-- ============================================
-- CREATE TEST/ADMIN USERS FOR DEVELOPMENT
-- ============================================

-- NOTE: You cannot directly insert auth users with passwords via SQL.
-- Supabase handles password hashing through its API.
-- 
-- To create the admin test user, use ONE of these methods:
--
-- METHOD 1: Use Supabase Dashboard (Easiest)
-- 1. Go to Authentication > Users
-- 2. Click "Add User"
-- 3. Email: admin@medconf.com
-- 4. Password: admin123
-- 5. Auto-confirm user: YES
--
-- METHOD 2: Use the signup form with these credentials:
-- Email: admin@medconf.com (or admin+test@gmail.com if using Gmail)
-- Password: admin123
--
-- After creating the auth user, run this script to add their profile:

-- ============================================
-- STEP 1: Add role column if not exists
-- ============================================
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS role TEXT;

-- ============================================
-- STEP 2: Create test user profiles
-- ============================================

-- Create admin profile (run AFTER creating auth user)
INSERT INTO user_profiles (id, email, role, specialty, region, full_name)
SELECT 
    id,
    email,
    'Admin',
    'General Practice',
    'London',
    'Admin User'
FROM auth.users 
WHERE email = 'admin@medconf.com'
ON CONFLICT (id) DO UPDATE SET
    role = EXCLUDED.role,
    specialty = EXCLUDED.specialty,
    region = EXCLUDED.region,
    full_name = EXCLUDED.full_name;

-- Create test doctor profile (run AFTER creating auth user)
INSERT INTO user_profiles (id, email, role, specialty, region, full_name)
SELECT 
    id,
    email,
    'Consultant',
    'Cardiology',
    'Manchester',
    'Test Doctor'
FROM auth.users 
WHERE email = 'test@medconf.com'
ON CONFLICT (id) DO UPDATE SET
    role = EXCLUDED.role,
    specialty = EXCLUDED.specialty,
    region = EXCLUDED.region,
    full_name = EXCLUDED.full_name;

-- Create notification preferences for admin
INSERT INTO notification_preferences (id, email_new_conferences, email_abstract_deadlines, email_price_changes, email_frequency)
SELECT 
    id,
    true,
    true,
    true,
    'daily'
FROM auth.users 
WHERE email = 'admin@medconf.com'
ON CONFLICT (id) DO UPDATE SET
    email_new_conferences = EXCLUDED.email_new_conferences,
    email_abstract_deadlines = EXCLUDED.email_abstract_deadlines,
    email_price_changes = EXCLUDED.email_price_changes,
    email_frequency = EXCLUDED.email_frequency;

-- Create notification preferences for test user
INSERT INTO notification_preferences (id, email_new_conferences, email_abstract_deadlines, email_price_changes, email_frequency)
SELECT 
    id,
    true,
    true,
    false,
    'weekly'
FROM auth.users 
WHERE email = 'test@medconf.com'
ON CONFLICT (id) DO UPDATE SET
    email_new_conferences = EXCLUDED.email_new_conferences,
    email_abstract_deadlines = EXCLUDED.email_abstract_deadlines,
    email_price_changes = EXCLUDED.email_price_changes,
    email_frequency = EXCLUDED.email_frequency;

-- ============================================
-- STEP 3: Verify test users
-- ============================================

-- Check all users and their profiles
SELECT 
    u.id,
    u.email,
    u.email_confirmed_at,
    u.created_at as user_created_at,
    p.role,
    p.specialty,
    p.region,
    p.full_name
FROM auth.users u
LEFT JOIN user_profiles p ON u.id = p.id
ORDER BY u.created_at DESC;

-- ============================================
-- QUICK SETUP INSTRUCTIONS
-- ============================================

-- FOR IMMEDIATE TESTING:
-- 
-- 1. Run this entire script in Supabase SQL Editor
-- 
-- 2. Go to Supabase Dashboard > Authentication > Users > Add User
--    - Email: admin@medconf.com
--    - Password: admin123
--    - Auto Confirm User: ✓ (check this box!)
--    - Click "Create User"
--
-- 3. Refresh this page and run the script again (it will add the profile)
--
-- 4. Now you can login at your app with:
--    Email: admin@medconf.com
--    Password: admin123
--
-- 5. OPTIONAL - Create another test user:
--    - Email: test@medconf.com
--    - Password: test123
--    - Auto Confirm User: ✓
--    Then run this script again

-- ============================================
-- ALTERNATIVE: Fix your existing user
-- ============================================

-- If you want to use your existing jaikishrajput@gmail.com:
INSERT INTO user_profiles (id, email, role, specialty, region, full_name)
SELECT 
    id,
    email,
    'Registrar',
    'Oncology',
    'East of England',
    'Jaikishan Rajput'
FROM auth.users 
WHERE email = 'jaikishrajput@gmail.com'
ON CONFLICT (id) DO UPDATE SET
    role = EXCLUDED.role,
    specialty = EXCLUDED.specialty,
    region = EXCLUDED.region,
    full_name = EXCLUDED.full_name;

-- Create notification preferences
INSERT INTO notification_preferences (id, email_new_conferences, email_abstract_deadlines, email_price_changes, email_frequency)
SELECT 
    id,
    true,
    true,
    false,
    'weekly'
FROM auth.users 
WHERE email = 'jaikishrajput@gmail.com'
ON CONFLICT (id) DO NOTHING;


