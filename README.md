# Weir Phillips Heritage SSDA Tracker

A browser-based NSW State Significant Development Application tracker for Weir Phillips Heritage.

## What is included

- WPH-branded Streamlit dashboard
- WPH logo
- Search and filters for LGA, status and development type
- NSW project map using OpenStreetMap tiles (no map API key)
- Project table and project detail view
- CSV export
- SQLite project database
- Automated daily NSW data refresh via GitHub Actions
- Ready for Streamlit Community Cloud

## Deploying the web app

1. Create a **private GitHub repository** called `weir-phillips-heritage-ssda-tracker`.
2. Upload the contents of this folder to the repository.
3. In GitHub, open **Actions → Refresh NSW SSDA data → Run workflow**.
4. Wait for the workflow to complete. It will create/update `data/tracker.sqlite3`.
5. In Streamlit Community Cloud, create a new app from the repository and select `app.py`.
6. The app can then be opened from any browser using its Streamlit URL.

The repository can remain private if the tracker is intended for internal WPH use.

## Automatic updates

The GitHub Action runs daily. It downloads the public NSW Planning Portal project information, updates the SQLite database, and commits the changed database back to the repository. The Streamlit app then reads the latest committed database.

## Important

The tracker is an independent tool using public NSW Planning Portal information. It is not an Urban Digest product and does not use Urban Digest's database or code.

Always verify critical planning information against the official NSW project record.
