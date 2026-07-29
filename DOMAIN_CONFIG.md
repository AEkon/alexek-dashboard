# 🔗 DNS Configuration Guide - hq.alexek.com

## 🎯 Objective
Configure your `alexek.com` domain to point `hq.alexek.com` to your Railway deployment.

## 📋 Prerequisites
- Railway project deployed (you'll get a URL like `https://your-project.up.railway.app`)
- Access to your domain registrar (where you bought alexek.com)
- Railway project settings open

## 🚀 Step-by-Step Configuration

### 1. Get Railway Domain Target

After deploying to Railway:
1. Go to [Railway Dashboard](https://railway.app)
2. Select your `alexek-dashboard` project
3. Go to **Settings** → **Domains**
4. Click **"Generate Domain"** if you haven't already
5. You'll see a URL like: `https://your-project-name.up.railway.app`

### 2. Add Custom Domain in Railway

1. In **Settings** → **Domains**
2. Click **"Add Domain"**
3. Enter: `hq.alexek.com`
4. Railway will show you the **DNS records** to add

### 3. Configure DNS at Your Registrar

Go to where you bought `alexek.com` (GoDaddy, Namecheap, Google Domains, etc.) and add:

#### **Option A: CNAME Record (Recommended)**

```
Type: CNAME
Name: hq
Value: your-project-name.up.railway.app
TTL: 3600 (or 1 hour)
```

#### **Option B: A Record (If Railway provides IP)**

```
Type: A
Name: hq
Value: [Railway-provided IP address]
TTL: 3600
```

### 4. Wait for DNS Propagation

DNS changes typically take 5-30 minutes, but can take up to 48 hours.

**Check propagation:**
```bash
# Check if DNS is working
dig hq.alexek.com

# Or use online tool:
# https://dnschecker.org/
```

### 5. Verify in Railway

1. Go back to Railway **Settings** → **Domains**
2. You should see a green checkmark next to `hq.alexek.com`
3. Railway will automatically provision SSL certificate

## 🧪 Test Your Domain

```bash
# Test backend health
curl https://hq.alexek.com/health

# Test jobs API
curl https://hq.alexek.com/api/jobs

# Test frontend
open https://hq.alexek.com
```

## 🎛️ Popular Registrar Instructions

### **GoDaddy**
1. Go to **My Products** → **DNS Management**
2. Add record with the above settings
3. Save changes

### **Namecheap**
1. Go to **Domain List** → **Manage** → **Advanced DNS**
2. Add **New Record**
3. Enter CNAME details
4. Save changes

### **Google Domains**
1. Go to **DNS** settings
2. Add **Custom record**
3. Enter CNAME details
4. Save changes

### **Cloudflare**
1. Go to **DNS** settings
2. Add **CNAME record**
3. Set **Proxy status** to **DNS only** (gray cloud)
4. Save changes

## 🔍 Troubleshooting

### **Domain not working?**

1. **Check DNS propagation:**
   ```bash
   dig hq.alexek.com
   ```
   Should point to Railway.

2. **Verify Railway configuration:**
   - Make sure domain is added in Railway settings
   - Check for any SSL errors in Railway dashboard

3. **Check for typos:**
   - Ensure `hq` (not `www` or `hq.`)
   - Verify Railway URL is correct

### **SSL certificate issues?**

Railway automatically provisions SSL certificates. If you see certificate errors:
1. Wait 15-30 minutes for Let's Encrypt
2. Check Railway logs for SSL errors
3. Ensure DNS is properly configured

### **Can access Railway URL but not custom domain?**

1. Check DNS propagation (step 4)
2. Verify CNAME target is correct
3. Clear browser DNS cache: restart browser or use incognito

## ✅ Success Checklist

- [ ] Railway project deployed
- [ ] Custom domain added in Railway settings
- [ ] DNS record configured at registrar
- [ ] DNS propagated (dig shows correct target)
- [ ] Railway shows green checkmark for domain
- [ ] `https://hq.alexek.com/health` returns healthy status
- [ ] `https://hq.alexek.com` shows dashboard

## 🎉 Once Complete

Your Squarespace Job Dashboard will be accessible at:
- **https://hq.alexek.com** (custom domain)
- **https://your-project.up.railway.app** (Railway URL - backup)

Both will work and redirect to the same application with automatic SSL!

## 🔄 Updates and Changes

After initial setup:
- **Code changes**: `git push` triggers auto-deploy
- **DNS changes**: Usually no updates needed
- **Railway URL**: Stays the same across deployments

Your dashboard is now live with professional branding at **hq.alexek.com**! 🚀