// Comma-separated lists such as IPwhiteList, technical_admins_email and postGresAdminEmails: the one parsing rule.
// split() keeps the spaces around each entry and an empty entry for a trailing or doubled comma, and
// replace(x, '\\s+', '') is a literal replace in Bicep, not a regex. So each entry is trimmed and empty entries are
// dropped. Case and order stay as given: IP ranges have no case to fold, and an email seeds its PostgreSQL
// administrator's name, so lower-casing would rename existing admins. Each template keeps its own guards and
// de-duplication. Object IDs have their own rule in objectIds.bicep.
// Importing a user-defined function compiles a template to ARM languageVersion 2.0, which changes how its 'existing'
// resources deploy. So only templates already on 2.0 (CmnAIfactoryNaming, esml-genai-1/11-integration) import it.
// The classic templates inline this exact body, and unit/test_list_entries.py pins every copy.

@export()
@description('Each entry trimmed, without empty entries, in the given order and case.')
func trimmedEntries(entries array) array => filter(map(entries, entry => trim(entry)), entry => !empty(entry))
