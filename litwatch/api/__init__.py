# litwatch.api is a package, so a sibling litwatch/api.py can never be imported.
# The frontend calls some endpoints by their short path (litwatch.api.<fn>),
# so those functions are re-exported here. Frappe resolves the dotted path to the
# same whitelisted function object, so both paths work:
#   litwatch.api.get_gstin_connections  ==  litwatch.api.gstin.get_gstin_connections

from litwatch.api.clients import create_client, set_active_client  # noqa: F401  (Dev Postman paths)
from litwatch.api.gstin import (  # noqa: F401
	connect_gstin,
	get_gstin_connections,
	get_gstin_otp_status,
	get_sync_log,
	get_sync_usage,
	resend_gstin_otp,
	run_all_gstin_sync,
	sync_gstin_notices,
	verify_gstin_otp,
)
