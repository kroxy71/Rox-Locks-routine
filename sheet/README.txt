Sharp Sheet
===========
Static website: index.html + model.js (probability model, no DOM) + app.js (UI) + data/*.csv.
It can be hosted as-is on any static host (Netlify, Vercel, GitHub Pages) or wrapped as an iPhone app
(for example a PWA, or Capacitor around this folder).

Refresh the data:   python collect.py <output folder>      (pulls ESPN's public JSON, about 1 minute)
Data source:        site.api.espn.com is an unofficial feed. A public or paid app should move to a licensed data provider.
                    dimers.com's free win-probability pages are also scraped (no public API) as an outside
                    reference line in Bet Lab, separate from the model's own number - it isn't blended in.
Model:              model.js - team ratings (ridge regression), Poisson goals for the NHL, normal margins for the NFL,
                    blended with the betting market, plus player prop estimates. Estimates only, not betting advice.

