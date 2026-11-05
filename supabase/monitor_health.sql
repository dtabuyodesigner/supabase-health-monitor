-- A public health RPC with no arguments, table reads, or elevated privileges.
CREATE FUNCTION public.monitor_health()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
AS $$ SELECT true $$;

REVOKE ALL ON FUNCTION public.monitor_health() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.monitor_health() TO anon, authenticated;
COMMENT ON FUNCTION public.monitor_health() IS
  'Read-only availability probe. Returns a constant; never reads application data.';
NOTIFY pgrst, 'reload schema';
