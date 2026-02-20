# VPS firewall: allow broker port for workers

The broker listens on **TCP 8000** (configurable via `BROKER_PORT`). For remote workers (e.g. a runner on your WSL machine) to reach it, that port must be reachable.

## Tailscale (recommended)

If the broker is bound to the VPS Tailscale IP (`BROKER_HOST=100.x.x.x`) and the worker runs on a machine that’s on the same tailnet (e.g. WSL with Tailscale), traffic stays on the tailnet. You must **allow TCP 8000 in your Tailscale policy** or the worker will get “No route to host” (ping may work; TCP is deny-by-default).

1. **Tailscale admin:** [login.tailscale.com](https://login.tailscale.com) → your tailnet → **Access controls**.
2. **Using Grants (recommended):** In the policy file, ensure the broker port is allowed. An “allow all” grant already permits it:
   ```json
   "grants": [
     { "src": ["*"], "dst": ["*"], "ip": ["*"] }
   ]
   ```
   To allow only the broker port on the VPS (tighter than allow-all), add an explicit grant (use your VPS node name, e.g. `urgoclaw`):
   ```json
   { "src": ["*"], "dst": ["urgoclaw"], "ip": ["tcp:8000"] }
   ```
3. **Save** the policy. Wait 30–60 seconds for propagation, then from the worker run: `curl -s http://VPS_TAILSCALE_IP:8000/health`.

Worker env: `BROKER_URL=http://VPS_TAILSCALE_IP:8000` (e.g. `http://100.107.41.32:8000`).

### firewalld on the VPS (Tailscale zone)

If the VPS uses **firewalld** and the Tailscale interface is in its own zone (e.g. `tailscale`), open TCP 8000 in that zone so workers can reach the broker over Tailscale:

```bash
sudo firewall-cmd --permanent --zone=tailscale --add-port=8000/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --zone=tailscale --list-ports   # should show 8000/tcp
```

Check the Tailscale zone name with `firewall-cmd --get-active-zones` (look for `tailscale0`).

## Cloud security group / firewall (public internet)

Most VPS providers (DigitalOcean, Linode, AWS, etc.) use a **cloud-level firewall** (security group). If you see **"No route to host"** or connection timeouts when curling `http://YOUR_VPS_IP:8000/health` from your worker machine, open inbound TCP **8000** in the provider’s console:

- **DigitalOcean:** Networking → Firewalls → create or edit a firewall → add rule: Inbound TCP port **8000**, sources: All IPv4 (or your IP).
- **Linode:** Firewalls → edit → add Inbound: TCP 8000, 0.0.0.0/0 (or your IP).
- **AWS:** Security group for the instance → Inbound rules → add TCP 8000 from 0.0.0.0/0 or your IP.

Then retest from your worker (e.g. WSL):

```bash
curl -s http://YOUR_VPS_IP:8000/health
# expect: {"ok":true,"ts_bound":true}
```

## Optional: UFW on the VPS

If your VPS uses **UFW** and you want to restrict port 8000 to certain IPs:

```bash
sudo ufw allow 8000/tcp
sudo ufw reload
sudo ufw status
```

If UFW is not installed, the cloud firewall is usually the only thing blocking; opening TCP 8000 there is sufficient.
