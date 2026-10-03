# Functional Requirements

| ID | Requirement | Current status |
|---|---|---|
| FR-01 | Display the landing page and navigation to application pages. | Implemented |
| FR-02 | Register a user and authenticate with username and password. | Implemented; bcrypt, JWT cookie, database-backed sessions |
| FR-03 | Accept home budget, rooms, room types, quantities (lights, fans, furniture, dining tables), style, platform and preference inputs. | Implemented |
| FR-04 | Generate a home recommendation plan through Gemini (offline fallback when unavailable). | Implemented |
| FR-05 | Accept party budget, event, guest, venue, food, and service inputs. | Implemented |
| FR-06 | Generate a party budget plan through Gemini (offline fallback). | Implemented |
| FR-07 | Accept jewelry budget, occasion, type, metal, and style preferences. | Implemented |
| FR-08 | Optionally use an outfit image for jewelry suggestions. | Implemented; validated, analysed in memory, not stored |
| FR-09 | Store generated recommendations per user and expose history endpoints. | Implemented in SQLite / PostgreSQL |
| FR-10 | Clear recommendation history. | Implemented; clears only the current user's plans |
| FR-11 | Present planner and history views through HTML templates. | Implemented |
| FR-12 | Show per-item shopping links, calculation table and remaining budget. | Implemented |
| FR-13 | Session info/data endpoints, logout revocation, idle-session cleanup. | Implemented |
| FR-14 | View one stored plan by id (`/recommendation-details/{id}`). | Implemented; owner only |
| FR-15 | Password reset ("Forgot password?"). | Not implemented (requires e-mail delivery) |

## Acceptance Notes

AI output is validated for shape and budget before use; invalid or over-budget responses fall back to an offline plan. Prices are planning estimates, not live prices.
