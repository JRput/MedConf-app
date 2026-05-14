# Email Verification Setup Guide for MedConf

This guide explains how to configure email verification for your MedConf application.

## ✅ What's Already Configured

The following has been set up for you:

1. **Custom Email Template** (`supabase/templates/confirm_signup.html`)
   - Professional design matching MedConf branding
   - Custom message: "Thank you for signing up to MedConf! Please click on the link below to verify your email. Kind regards, MedConf Team"
   - Includes plain text fallback for better deliverability

2. **Email Confirmations Enabled** (`supabase/config.toml`)
   - Users must verify their email before they can sign in
   - Custom template configured with subject "Verify Your Email - MedConf"

3. **SignUp Flow Updated** (`medconf-website/src/hooks/useAuth.ts`)
   - Automatically includes email redirect URL
   - Redirects to `/auth/callback` after verification

4. **Callback Handler Enhanced** (`medconf-website/src/app/auth/callback/route.ts`)
   - Handles verification success and errors
   - Redirects to conferences page on success
   - Shows error message if verification fails

## 🧪 Testing in Development

For local development, Supabase uses Inbucket (a built-in email testing tool):

1. Start your Supabase local instance:
   ```bash
   supabase start
   ```

2. Access Inbucket at: http://localhost:54324
   - All emails sent during development will appear here
   - You can click the verification links directly from Inbucket

3. Test the signup flow:
   - Go to http://localhost:3000/auth/signup
   - Create a test account
   - Check Inbucket for the verification email
   - Click the verification link
   - You should be redirected to /conferences

## 🚀 Production SMTP Setup

For production, you need to configure a real SMTP provider. Here are the recommended options:

### Option 1: Resend (Recommended - Best for Developers)

Resend is modern, developer-friendly, and has generous free tier:

1. Sign up at https://resend.com
2. Get your API key from the dashboard
3. Configure your domain (optional but recommended for better deliverability)
4. Update `supabase/config.toml`:

```toml
[auth.email.smtp]
enabled = true
host = "smtp.resend.com"
port = 465
user = "resend"
pass = "env(RESEND_API_KEY)"
admin_email = "noreply@yourdomain.com"
sender_name = "MedConf Team"
```

5. Add your API key to your environment variables:
   ```bash
   RESEND_API_KEY=re_xxxxxxxxxxxxx
   ```

### Option 2: SendGrid

1. Sign up at https://sendgrid.com
2. Create an API key with "Mail Send" permissions
3. Update `supabase/config.toml`:

```toml
[auth.email.smtp]
enabled = true
host = "smtp.sendgrid.net"
port = 587
user = "apikey"
pass = "env(SENDGRID_API_KEY)"
admin_email = "noreply@yourdomain.com"
sender_name = "MedConf Team"
```

### Option 3: AWS SES (Best for Scale)

1. Set up AWS SES and verify your domain
2. Create SMTP credentials
3. Update `supabase/config.toml`:

```toml
[auth.email.smtp]
enabled = true
host = "email-smtp.us-east-1.amazonaws.com"  # Change region as needed
port = 587
user = "env(AWS_SES_SMTP_USER)"
pass = "env(AWS_SES_SMTP_PASSWORD)"
admin_email = "noreply@yourdomain.com"
sender_name = "MedConf Team"
```

## 📧 Email Deliverability Best Practices

To ensure your emails reach the inbox:

### 1. Domain Authentication (Highly Recommended)

Set up these DNS records for your sending domain:

- **SPF Record**: Authorizes which servers can send email from your domain
- **DKIM**: Adds a digital signature to your emails
- **DMARC**: Tells email providers how to handle unauthenticated emails

Most SMTP providers will give you specific DNS records to add.

### 2. Use a Custom Domain

Instead of `noreply@gmail.com`, use `noreply@medconf.com`:
- More professional
- Better deliverability
- Higher trust from users
- Less likely to be marked as spam

### 3. Monitor Email Metrics

Track these metrics in your SMTP provider dashboard:
- **Delivery Rate**: Should be >95%
- **Open Rate**: Verification emails typically have 80-90% open rate
- **Bounce Rate**: Should be <5%
- **Spam Complaints**: Should be <0.1%

## 🔧 Configuration Checklist

Before deploying to production:

- [ ] SMTP provider configured in `supabase/config.toml`
- [ ] API keys added to environment variables (never commit these!)
- [ ] Custom domain configured and verified with SMTP provider
- [ ] SPF, DKIM, and DMARC DNS records added
- [ ] Test email sending from production environment
- [ ] Verify emails land in inbox (not spam)
- [ ] Test verification link works correctly
- [ ] Monitor bounce rate and deliverability metrics

## 🐛 Troubleshooting

### Emails not sending

1. Check Supabase logs: `supabase functions logs`
2. Verify SMTP credentials are correct
3. Ensure firewall allows outbound connections on port 587/465
4. Check if SMTP provider has rate limits

### Emails going to spam

1. Add SPF/DKIM/DMARC DNS records
2. Use a custom domain (not Gmail/Yahoo)
3. Warm up your sending domain (start with low volume)
4. Ensure email content isn't too promotional
5. Include plain text version (already done)

### Verification link not working

1. Check `emailRedirectTo` URL is correct
2. Ensure callback route is accessible
3. Check Supabase allowed redirect URLs in dashboard
4. Verify the verification link hasn't expired (default: 1 hour)

## 📱 Testing Checklist

Test these scenarios before going live:

- [ ] Sign up with new email → receive verification email
- [ ] Click verification link → redirected to /conferences
- [ ] Sign up with already-used email → appropriate error
- [ ] Try to log in without verifying → blocked
- [ ] Verification link expires after 1 hour
- [ ] Resend verification email works
- [ ] Emails render correctly on mobile devices
- [ ] Plain text version is readable
- [ ] Spam folder check (test with Gmail, Outlook, etc.)

## 🔐 Security Notes

- Never commit SMTP credentials to Git
- Use environment variables for all secrets
- Rotate API keys regularly
- Monitor for suspicious email activity
- Set up rate limiting to prevent abuse
- Consider implementing captcha on signup

## 📚 Additional Resources

- [Supabase Auth Email Documentation](https://supabase.com/docs/guides/auth/auth-email)
- [Resend Documentation](https://resend.com/docs)
- [SendGrid SMTP Setup](https://docs.sendgrid.com/for-developers/sending-email/integrating-with-the-smtp-api)
- [Email Deliverability Guide](https://www.mailgun.com/blog/email-deliverability-guide/)

## 🎯 Quick Start for Production

If you want to go live quickly:

1. Sign up for Resend (5 minutes, free tier is generous)
2. Get your API key
3. Update `supabase/config.toml` with the configuration above
4. Add `RESEND_API_KEY` to your environment
5. Deploy and test!

That's it! Your users will now receive beautiful verification emails with your custom message.


