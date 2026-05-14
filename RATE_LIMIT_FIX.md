# Fix Email Rate Limit in Supabase

## Option 1: Adjust Rate Limit in Dashboard (Fastest)

1. Go to your Supabase Dashboard: https://supabase.com/dashboard
2. Select your project (ystpjjhfgfraxcnvbish)
3. Go to **Authentication** > **Rate Limits**
4. Find "Email Rate Limit" or "Auth Rate Limit"
5. Increase the limit or disable it temporarily for testing
6. Save changes

## Option 2: Manually Verify Existing User (For Immediate Testing)

If you want to test RIGHT NOW without waiting, manually verify the existing user:

1. Go to Supabase Dashboard > **Authentication** > **Users**
2. Click on the user `jaikishrajput@gmail.com`
3. Look for "Email Confirmed" status
4. If it says "Unconfirmed", click to manually confirm it
5. Then run this SQL to create their profile:

```sql
-- Add the role column first (if you haven't already)
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS role TEXT;

-- Insert profile for existing user
INSERT INTO user_profiles (id, email, role, specialty, region)
SELECT 
    id,
    email,
    'Registrar',
    'Oncology',
    'East of England'
FROM auth.users 
WHERE email = 'jaikishrajput@gmail.com'
ON CONFLICT (id) DO NOTHING;
```

6. Now you can log in with that email and test the app!

## Option 3: Clear Rate Limit via SQL (Advanced)

Run this in Supabase SQL Editor to check rate limit status:

```sql
-- Check auth rate limit entries
SELECT * FROM auth.mfa_factors LIMIT 10;
```

Note: Rate limits are usually stored in memory/redis, so you may need to wait or use Option 1.

## Option 4: Use Different Email Format

Gmail ignores dots and supports + addressing:
- If you used: test@gmail.com
- Try: t.e.s.t@gmail.com or test+1@gmail.com or test+2@gmail.com

All will deliver to the same inbox but Supabase treats them as different emails!


