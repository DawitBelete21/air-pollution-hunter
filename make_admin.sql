-- Run this only AFTER you have created your own account on the website.
-- Replace the value below with your exact username.
-- This promotes that one account to administrator.
update public.profiles
set role = 'admin'
where username = 'dawit123';

-- Verify the result. The role should show "admin".
select username, role
from public.profiles
where username = 'dawit123';
