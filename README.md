XAMPP-cheat – AI-Powered SQL Query Generator & Verifier
This Python script automatically generates, runs, and verifies MySQL/MariaDB queries based on a database schema exported from XAMPP (.sql) and a plain-text list of tasks (.txt).

Features
Automatic Schema Extraction: Extracts CREATE TABLE statements from the .sql file so large databases do not exceed AI token limits.

Groq AI Integration: Automatically picks the best available text model and falls back to alternative models on rate limits or availability issues.

Live MySQL Verification: Connects to your local XAMPP MySQL server, executes generated SELECT queries, and writes the result rows to the output file.

Self-Healing Loop: If a query raises a MySQL error, it sends the error message back to the AI and attempts to fix the query.

Prerequisites
Python 3.8+

XAMPP installed with the MySQL service running

A free Groq API key (https://console.groq.com/)

Installation
Clone the repository:
git clone https://github.com/Csanad-0/XAMPP-cheat.git
cd XAMPP-cheat

Install the required packages:
pip install -r requirements.txt

Usage
Prepare the database:

Import your database into XAMPP phpMyAdmin (localhost/phpmyadmin).

Place your exported .sql file in the project directory.

Configure the script:
Open your Python script and update the database and file names to match your setup:
DB_NEV = "your_database_name"
SQL_FAJL = "database.sql"
FELADAT_FAJL = "tasks.txt"
KIMENET_FAJL = "answers.txt"

Set your API key:
Set the GROQ_API_KEY environment variable in your terminal:

Windows (CMD): set GROQ_API_KEY=gsk_your_api_key_here

Windows (PowerShell): $env:GROQ_API_KEY="gsk_your_api_key_here"

Linux / macOS: export GROQ_API_KEY="gsk_your_api_key_here"

Run the script:
python solver.py
(Replace solver.py with whatever filename you saved your script under.)

Check the results:
Generated SQL queries, short explanations, and query execution outputs are saved to answers.txt.Ű

foglalas_id | vendeg_neve | szobaszam | ejszakak_szama | kedvezmenyes_szallasi_dij

python -m pip install openai mysql-connector-python
