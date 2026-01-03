# Family Tracker

## Overview

Family Tracker is a web application that allows users to track and share locations with friends and family members. The app features user authentication, friend management, and real-time location tracking using interactive maps. Users can register, log in, add friends, and view their locations on private maps.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Framework
- **Flask (Python)**: The application uses Flask as the web framework for handling HTTP requests, routing, and rendering templates
- **Session Management**: Uses Flask-Session with filesystem storage for user session persistence
- **Authentication**: Custom login_required decorator pattern with password hashing via Werkzeug security utilities

### Database
- **SQLite**: Uses SQLite with a file-based database (`family.db`) for data persistence
- **Schema**: Database schema defined in `schema.sql` file, initialized via `init_db()` function
- **Connection Pattern**: Uses `sqlite3.Row` factory for dictionary-like row access

### Frontend
- **Jinja2 Templates**: Server-side rendering with template inheritance (`layout.html` as base)
- **Bootstrap 5**: CSS framework for responsive UI components and styling
- **Leaflet.js**: JavaScript mapping library for interactive location visualization
- **OpenStreetMap**: Tile provider for map rendering

### Key Features
1. **User Authentication**: Registration, login, logout with password hashing
2. **Friend System**: Search users and add friends with bidirectional relationships
3. **Location Tracking**: GPS-based position tracking using browser geolocation API
4. **Private Maps**: Display friend locations on interactive maps with real-time updates

### API Structure
- `/api/locations`: Returns location data for authenticated users
- Standard REST-like routes for authentication (`/login`, `/register`, `/logout`)
- Friend management routes (`/searchf`, `/add_friend`)

## External Dependencies

### Python Packages
- **Flask**: Web framework
- **Flask-Session**: Server-side session management
- **Werkzeug**: Password hashing and security utilities
- **sqlite3**: Database connectivity (Python standard library)

### Frontend Libraries (CDN)
- **Bootstrap 5.3.0**: UI component framework
- **Leaflet 1.9.4**: Interactive mapping library
- **OpenStreetMap**: Map tile service
- **Google Fonts (Inter)**: Typography

### Configuration Files
- **components.json**: Contains shadcn/ui configuration (appears to be for a potential React/TypeScript frontend, possibly for future development)
- **script/build.ts**: Build script suggesting potential Node.js/TypeScript tooling for frontend bundling with Vite and esbuild