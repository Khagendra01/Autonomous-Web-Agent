# 🔥 Oracle Cloud Firewall Configuration

## Critical: Oracle Cloud Security Rules

The web interface timeout is likely because **Oracle Cloud has its own firewall** that needs to be configured separately from UFW.

## Steps to Open Port 80 in Oracle Cloud

### Method 1: Via Oracle Cloud Console (Recommended)

1. **Log in to Oracle Cloud Console**
   - Go to: https://cloud.oracle.com
   - Sign in to your account

2. **Navigate to Networking**
   - Click **"Networking"** → **"Virtual Cloud Networks"**
   - Select your VCN (Virtual Cloud Network)

3. **Edit Security List**
   - Click **"Security Lists"** in the left menu
   - Click on your **default security list**
   - Click **"Add Ingress Rules"**

4. **Add HTTP Rule**
   - **Source Type:** CIDR
   - **Source CIDR:** 0.0.0.0/0 (to allow from anywhere)
   - **IP Protocol:** TCP
   - **Destination Port Range:** 80
   - **Description:** Allow HTTP access
   - Click **"Add Ingress Rules"**

5. **Add HTTPS Rule (Optional)**
   - Repeat above but use port **443** for HTTPS

### Method 2: Via Command Line (OCI CLI)

If you have OCI CLI installed:
```bash
oci network security-list ingress-rule create \
  --security-list-id <your-security-list-id> \
  --description "Allow HTTP" \
  --source-type CIDR \
  --source "0.0.0.0/0" \
  --protocol "6" \
  --tcp-options '{"destinationPortRange":{"max":80,"min":80}}'
```

## Verify Current Security Rules

1. In Oracle Cloud Console
2. Go to: **Networking** → **Virtual Cloud Networks** → Your VCN
3. Click **"Security Lists"**
4. Check if port 80 is allowed

## Test After Configuration

After adding the security rule:
```bash
# From your Windows machine
curl http://129.80.169.184
# Or open in browser: http://129.80.169.184
```

## Current Status

✅ UFW firewall: Active, port 80 allowed  
✅ Nginx: Installing/Configuring  
✅ Web app: Running on port 5000  
⚠️ **Oracle Cloud Security Rules: NEED TO BE CONFIGURED**

**This is the most likely cause of the connection timeout!**

