# Surhan Scanner Comprehensive Production Certification Test Matrix

## 1. Upload Test Matrix

### Normal Upload Cases
- PDF single page
- PDF multi-page
- JPG image
- JPEG image
- PNG image
- TIF image
- TIFF image
- Arabic file name
- English file name
- Long file name
- File name with spaces
- File name with symbols
- Private file upload
- Public file upload if allowed
- Attachment Only mode
- Direct attach to Attach field
- Direct attach to Attach Image field
- Attach to child table if configured

### Negative Upload Cases
- Missing scan_token
- Fake scan_token
- Expired scan_token
- Reused scan_token
- Wrong target doctype
- Deleted target document
- Deleted scanner rule
- Empty file
- Corrupted PDF
- Wrong extension
- Executable file .exe
- Script file .js
- PHP file .php
- Oversized file
- MIME mismatch
- PDF renamed to .jpg
- JPG renamed to .pdf
- Upload without file payload
- Upload with duplicate file name
- Upload during DB transaction failure
- Upload when disk is almost full

## 2. Agent Connectivity Test Matrix

### Normal Agent Cases
- Agent heartbeat with valid token
- Agent heartbeat without token
- Agent heartbeat with invalid token
- Agent update manifest with valid token
- Agent update manifest without token
- Agent update status reporting
- Agent online status
- Agent offline status
- Agent stale status

### Scanner Device Cases
- Scanner connected
- Scanner disconnected
- Scanner busy
- Scanner paper jam
- Scanner feeder empty
- Scanner duplex enabled
- Scanner duplex disabled
- Scanner color mode
- Scanner grayscale mode
- Scanner resolution changes
- Multiple scanner devices on same PC
- Multiple PCs with same user
- Multiple users from same department

## 3. Security Test Matrix

- Guest API access without token
- Guest API access with fake token
- Authenticated user without role
- Authenticated user with correct role
- Administrator access
- Unauthorized file download
- Attempt to access private file URL
- Attempt to enumerate scan sessions
- Attempt to reuse old scan session
- Attempt to upload dangerous file
- Attempt to modify scanner settings without permission
- Token leakage scan
- Error log leakage scan
- Rate abuse test
- Replay attack test
- Concurrent token use test

## 4. Archiving and Storage Test Matrix

- Archive to File DocType
- Archive to target document attachment
- Archive to child table
- Archive with custom file name
- Archive with barcode metadata
- Archive with duplicate barcode
- Archive to private files
- Archive to public files if enabled
- Storage path validation
- File deletion cleanup
- Orphan File cleanup
- Orphan Scanner Log cleanup
- Retention policy simulation
- Large archive volume simulation
- Backup includes database
- Backup includes private files
- Backup includes public files
- Restore test

## 5. Failure and Recovery Test Matrix

- Network drop during upload
- Agent timeout
- Frappe worker stopped
- Redis unavailable
- MariaDB slow query
- Disk full simulation
- Permission denied on private files folder
- Invalid PDF parser error
- Concurrent uploads to same target
- Concurrent uploads with same filename
- Browser refresh during scan
- User logout during scan
- Server restart during upload
- Agent retry behavior
- Upload retry count validation
- Partial failure cleanup

## 6. Load and Stress Test Matrix

### User Load Levels
- 10 users
- 25 users
- 50 users
- 100 users
- 200 users

### Upload Load Levels
- 10 simultaneous uploads
- 25 simultaneous uploads
- 50 simultaneous uploads
- 100 simultaneous uploads
- 200 simulated upload sessions

### Measurements
- HTTP status codes
- Average response time
- Max response time
- Failed requests
- DB growth
- File count growth
- Worker queue delay
- CPU usage
- RAM usage
- Disk usage
- Redis health
- MariaDB health
- Error Log count

## 7. Acceptance Criteria

The system is production-ready only if:

- No Python compile errors
- No migration errors
- No 500 errors in normal use
- No secret/token leakage
- No unauthorized access
- No dangerous file accepted
- Upload token is single-use
- Expired tokens are rejected
- Fake tokens are rejected
- File records match actual files
- Scanner logs match upload results
- Cleanup does not leave orphan test data
- Backup and restore are verified
- 200-user simulation does not break the system
- CPU/RAM/Disk remain within safe limits
- Error logs remain clean after test
