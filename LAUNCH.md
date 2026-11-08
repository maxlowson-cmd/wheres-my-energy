# Putting the site live

Everything is ready in this folder. These steps need your own accounts.

## 1. Put the folder on GitHub

1. Create a free account at [github.com](https://github.com).
2. Install [GitHub Desktop](https://desktop.github.com) and sign in.
3. Choose **File > Add local repository**, pick this `wheres-my-energy` folder, and accept the offer to create a repository.
4. Make the first commit, then click **Publish repository**.
5. Name it `wheres-my-energy` and **untick "Keep this code private"**. The free website and free scheduled builds rely on it being public.

## 2. Turn the website on

1. On the repository's page on GitHub, open **Settings > Pages**.
2. Under **Source**, choose **GitHub Actions**.
3. Open the **Actions** tab, choose **Build and publish the site**, and click **Run workflow**.
4. When it goes green, the site is live at `https://YOUR-USERNAME.github.io/wheres-my-energy/`.

It then rebuilds itself about every 30 minutes. GitHub can run scheduled jobs a little late at busy times.

## 3. Add your own domain (optional)

1. Buy the domain from any registrar.
2. In **Settings > Pages > Custom domain**, enter it and save.
3. At the registrar, add the DNS records that [GitHub's custom domain guide](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site) lists.
4. Once GitHub confirms the domain, tick **Enforce HTTPS**.

## Keeping it running

- If a build fails, the last good version stays online. Failures show in the **Actions** tab.
- GitHub pauses scheduled jobs on a public repository after 60 days with no activity. The monthly update of the 12-month averages counts as activity, so this shouldn't happen.
- The renewables register in `data/repd.csv` is updated quarterly and needs replacing by hand.
