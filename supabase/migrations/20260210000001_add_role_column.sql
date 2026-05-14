-- Add role column to user_profiles table
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS role TEXT;

-- Create index for role column for better query performance
CREATE INDEX IF NOT EXISTS idx_user_profiles_role ON user_profiles(role);


