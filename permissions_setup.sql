-- Run once in Supabase SQL Editor after the original database setup.
-- RLS policies remain the security boundary; these grants let authenticated
-- users reach the tables through the Supabase Data API.

grant usage on schema public to authenticated;

grant select on public.profiles to authenticated;

grant select, insert, delete on public.uploads to authenticated;
grant select, insert, delete on public.sensor_readings to authenticated;

grant usage, select on sequence public.sensor_readings_id_seq to authenticated;

grant execute on function public.is_admin() to authenticated;

-- Storage access is still restricted by the storage.objects RLS policies
-- created in the original setup SQL.
