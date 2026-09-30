# The demo on a VM

The same single-container image as the Hugging Face Space
(`deploy/huggingface`), on any Linux VM with Docker, behind Caddy for
HTTPS. The public demo runs on an Oracle Cloud Always Free Ampere
instance; nothing below is specific to Oracle except the firewall steps.

## 1. The machine

In the Oracle Cloud console, Compute → Instances → Create instance:

- **Image:** Canonical Ubuntu 24.04.
- **Shape:** Ampere, `VM.Standard.A1.Flex`, 2 OCPU and 12 GB. Anything up to
  4 OCPU and 24 GB is within Always Free. If the region reports no capacity,
  try another availability domain or a smaller shape.
- **Networking:** a new virtual cloud network with a public subnet, and a
  public IPv4 address.
- **SSH key:** paste your public key.

Once it is running, open the instance's subnet → security list → add two
ingress rules: source `0.0.0.0/0`, TCP, destination ports `80` and `443`.

Oracle reclaims Always Free instances that sit idle for a week (CPU, network
and memory all under 20%). A demo that is rarely visited qualifies; upgrading
the account to Pay As You Go keeps Always Free resources free and ends the
reclaiming.

## 2. A hostname

Caddy needs a hostname that resolves to the VM to obtain a certificate. Any
domain works; a free one is a DuckDNS subdomain (duckdns.org, pointed at the
VM's public IP). Without one, the demo still runs over plain HTTP at the IP
address (`SITE_ADDRESS=:80`).

## 3. Set up and deploy

On the VM:

```bash
git clone https://github.com/eklavya072/Meridian-AI-Governance-Intelligence.git ~/meridian
sudo ~/meridian/deploy/vm/bootstrap.sh
```

Log in again (for the docker group), then provide the two things that are not
in the repository, in `/srv/meridian`:

- `seed/`: `seed.sql` and `chroma/`, made by
  `deploy/huggingface/make_seed.sh` on the machine that holds the showcase
  analyses, copied over with `rsync -a`.
- `.env`, readable only by you (`chmod 600`):

  ```
  GEMINI_API_KEY=<one key>
  SITE_ADDRESS=meridian.example.org
  SITE_URL=https://meridian.example.org
  ```

Then:

```bash
~/meridian/deploy/vm/deploy.sh
```

The first build takes several minutes; later ones reuse the cached layers.

## Updating

```bash
git -C ~/meridian pull --ff-only && ~/meridian/deploy/vm/deploy.sh
```

Each deploy starts a new container from the showcase state, so workspaces
made on the previous one are cleared. `docker compose -f
~/meridian/deploy/vm/compose.yml --env-file /srv/meridian/.env logs -f
meridian` follows the app's log.
