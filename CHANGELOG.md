# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<<<<<<< HEAD
## [2.1.1] - 2026-03-24
>>>>>>> 1b60e72 (Version 2.1.1: Improved availability responsiveness)

### Added
- Separate polling intervals for different data types (availability vs schedule)
- Force full data refresh on Home Assistant restart/integration reload

### Changed
- **Improved availability responsiveness**: Availability status now updates every 15 seconds (down from 60 seconds)
- **Optimized schedule polling**: Schedule data now updates every 5 minutes instead of every poll
- **Faster initial data load**: All data is immediately fetched when the integration starts or restarts

### Fixed
- Availability switch not reflecting external changes made outside Home Assistant within a reasonable time

### Technical
- Added configurable `schedule_scan_interval` option (default: 300 seconds)
- Reduced default `scan_interval` to 15 seconds for faster availability updates
- Added first-update flag to ensure complete data refresh on startup