# 🏠 Ingress Guide - Multi-App Proxy

## What is Ingress?

**Ingress** is a Home Assistant feature that allows integrating add-ons directly into the Home Assistant interface without exposing additional ports.

## 🎯 Benefits of Ingress

### 1. **Security** 🔐
- ✅ Uses Home Assistant authentication
- ✅ No additional ports to expose
- ✅ Benefits from Home Assistant SSL
- ✅ Protected by your HA login

### 2. **Simplicity** 🚀
- ✅ One-click access from HA interface
- ✅ No network configuration needed
- ✅ No port management
- ✅ No external reverse proxy required

### 3. **Integration** 🔗
- ✅ Icon in the sidebar
- ✅ "OPEN WEB UI" button in the add-on
- ✅ Same domain as Home Assistant
- ✅ Consistent interface

## 📊 Comparison: Ingress vs Traditional Port

| Aspect | Ingress | Traditional Port |
|--------|---------|-----------------|
| **Authentication** | ✅ Automatic (HA) | ❌ Must manage separately |
| **SSL/HTTPS** | ✅ If HA has it | ⚠️ Must configure |
| **Network configuration** | ✅ None | ❌ Open ports |
| **Access** | Via HA interface | Direct URL |
| **Security** | ✅ High | ⚠️ Depends on config |
| **Simplicity** | ✅ Very simple | ⚠️ More complex |

## 🔧 How Ingress Works

### Architecture

```
┌─────────────────────────────────────────┐
│     User (browser)                      │
└─────────────────┬───────────────────────┘
                  │ HTTPS (if configured)
                  ▼
┌─────────────────────────────────────────┐
│      Home Assistant                     │
│  ┌───────────────────────────────────┐  │
│  │  HA Authentication                │  │
│  └───────────┬───────────────────────┘  │
│              │                           │
│              ▼                           │
│  ┌───────────────────────────────────┐  │
│  │  Ingress Proxy                    │  │
│  │  /api/hassio_ingress/TOKEN        │  │
│  └───────────┬───────────────────────┘  │
└──────────────┼───────────────────────────┘
               │ Port 8099 (internal)
               ▼
┌─────────────────────────────────────────┐
│  Multi-App Proxy Add-on                 │
│  (Nginx on port 8099)                   │
└─────────────────┬───────────────────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
    ┌─────┐   ┌─────┐   ┌─────┐
    │App 1│   │App 2│   │App 3│
    └─────┘   └─────┘   └─────┘
```

### Request Flow

1. **User** clicks the icon in HA
2. **Home Assistant** verifies authentication
3. **Ingress** generates a unique token
4. **Ingress Proxy** redirects to the add-on with the token
5. **Add-on** receives the request on port 8099
6. **Nginx** serves the interface or proxies to apps
7. **Response** returned to the user

## 🔐 Security with Ingress

### What is Protected

- ✅ Access to the proxy interface
- ✅ Application list
- ✅ All add-on routes

### What is NOT Protected

- ⚠️ The applications themselves (they keep their own auth)
- ⚠️ Direct connections to apps (if ports are exposed)

### Recommendations

1. **Keep your applications on a local network** not accessible from the Internet
2. **Use strong passwords** on Home Assistant
3. **Enable 2FA** on Home Assistant if possible
4. **Don't share** your HA credentials
5. **Monitor logs** to detect suspicious access

## 📱 Practical Usage

### Access via Sidebar

1. Enable **"Show in sidebar"** in the add-on
2. An icon 📊 appears in the left sidebar
3. Click it to access the interface
4. Enjoy your applications!

### Access via Add-on

1. Go to **Supervisor** → **Multi-App Proxy**
2. Click **"OPEN WEB UI"** at the top
3. Interface opens in a new tab
4. Already authenticated via HA!

### Generated URLs

Home Assistant generates URLs like:
```
https://your-ha.com/api/hassio_ingress/UNIQUE_TOKEN/
```

The TOKEN changes with each session for extra security.

## 🔧 Configuring Ingress in the Add-on

### In config.yaml

```yaml
# Enable Ingress
ingress: true

# Internal port used by Ingress
ingress_port: 8099

# Icon in the sidebar
panel_icon: mdi:view-dashboard

# Title in the sidebar
panel_title: Multi-App Proxy

# Accessible to non-admin users
panel_admin: false
```

### Environment Variables

The add-on automatically receives:

```bash
INGRESS_ENTRY="/api/hassio_ingress/TOKEN"
```

This variable allows the proxy to adapt to the Ingress context.

## 🚫 Ingress Limitations

### Technical Limitations

1. **No direct access**: Only via Home Assistant
2. **Token timeout**: Sessions expire after inactivity
3. **No subdomains**: Cannot create dedicated subdomains
4. **Certificates**: Uses HA's certificate (cannot have a separate one)

### When NOT to Use Ingress

❌ If you want public access without HA
❌ If you need a dedicated subdomain
❌ If you want to share access without HA login
❌ If you have apps that break with a base path

### Alternatives to Ingress

If Ingress doesn't suit you:

1. **Port mapping**: Expose a port (e.g., 8099)
2. **Nginx Proxy Manager**: Separate reverse proxy
3. **Traefik**: For automatic SSL management
4. **Cloudflare Tunnel**: For secure external access

## 💡 Tips & Tricks

### Tip 1: Quick Bookmark

Create a bookmark of the Ingress URL for quick access:
```
https://your-ha.com/hassio/ingress/multiappproxy
```

### Tip 2: Dashboard Widget

Add a button to your HA dashboard:

```yaml
type: button
name: My Applications
icon: mdi:apps
tap_action:
  action: url
  url_path: /hassio/ingress/multiappproxy
```

### Tip 3: Check Status

Monitor the add-on status:

```yaml
type: entity
entity: sensor.multiappproxy_status
```

### Tip 4: Real-time Logs

Keep the **Log** tab open during debugging.

## 🔍 Debugging Ingress

### Verify Ingress is Working

1. Open the add-on logs
2. Look for: `Ingress mode enabled`
3. Check the displayed base path

### Common Issues

#### "Session expired"
**Cause**: Token expired
**Solution**: Reload the page

#### "502 Bad Gateway"
**Cause**: Add-on not started or crashed
**Solution**: Check logs, restart

#### "403 Forbidden"
**Cause**: Authentication issue
**Solution**: Reconnect to HA

#### Empty Interface
**Cause**: Configuration error
**Solution**: Check config and logs

## 📚 Resources

### Official Documentation

- [Home Assistant Ingress](https://developers.home-assistant.io/docs/add-ons/presentation#ingress)
- [Add-on Communication](https://developers.home-assistant.io/docs/add-ons/communication)

### Support

- GitHub Issues
- Home Assistant Forum
- Home Assistant Discord

## ✅ Ingress Checklist

Configuration is correct if:

- [ ] `ingress: true` in config.yaml
- [ ] `ingress_port: 8099` defined
- [ ] `panel_icon` and `panel_title` configured
- [ ] Nginx listening on port 8099
- [ ] `INGRESS_ENTRY` variable read in code
- [ ] Logs show "Ingress mode enabled"
- [ ] "OPEN WEB UI" button works
- [ ] Sidebar shows icon (if enabled)

---

**Ingress makes access to your applications simple and secure! 🎉**
