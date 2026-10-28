-- First create ledger_server as a LOGIN role with a generated password stored
-- only in your hosting secret store. Do not put that password in this file.
-- Example role attributes: NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION.
GRANT USAGE ON SCHEMA ledger TO ledger_server;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ledger TO ledger_server;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ledger TO ledger_server;
DROP POLICY IF EXISTS server_accounts ON ledger.accounts;
CREATE POLICY server_accounts ON ledger.accounts TO ledger_server USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS server_transactions ON ledger.transactions;
CREATE POLICY server_transactions ON ledger.transactions TO ledger_server USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS server_transfers ON ledger.transfers;
CREATE POLICY server_transfers ON ledger.transfers TO ledger_server USING (true) WITH CHECK (true);
-- These policies authorize the trusted server role for this shared demo.
-- PUBLIC, anon, and authenticated receive no access to the private schema.
