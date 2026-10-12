#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/../../full_app/production_frontend"
npm run build && npm test && npm run test:browser
