#!/bin/bash
source ~/ONE-Backend/One-Middleware/venv/bin/activate
cd ~/ONE-Backend/One-Middleware
python manage.py runserver 0.0.0.0:8020
