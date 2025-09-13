# Lead Generation Platform

A comprehensive B2B lead generation and cold email automation platform built with FastAPI, featuring AI-powered email personalization, LinkedIn scraping, and multi-tenant RAG capabilities.

## 🚀 Product Overview

### What This Platform Does

This lead generation platform automates the entire B2B sales outreach process:

1. **Lead Discovery**: Search and extract potential leads from various sources
2. **Data Enrichment**: Scrape LinkedIn profiles and company information
3. **AI-Powered Email Generation**: Create personalized cold emails using AI
4. **Email Campaign Management**: Send and track bulk email campaigns
5. **Intelligent Follow-ups**: Analyze email responses and generate appropriate replies
6. **Knowledge Management**: RAG (Retrieval-Augmented Generation) system for company-specific context

### Key Features

- **Multi-tenant Architecture**: Support for multiple organizations
- **AI Email Personalization**: Uses OpenAI/LangChain for contextual email generation
- **LinkedIn Integration**: Automated profile and company data scraping
- **Spam Score Analysis**: Built-in email deliverability optimization
- **Real-time Search**: Google Search integration for lead discovery
- **Email Analytics**: Comprehensive tracking and reporting
- **Knowledge Base**: Document ingestion and RAG-powered responses

## 🏗️ Technical Architecture

### Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: PostgreSQL with Prisma ORM
- **AI/ML**: OpenAI GPT, LangChain, Custom embeddings
- **Authentication**: JWT-based auth
- **Email**: SMTP integration with tracking
- **Search**: Google Search API
- **Scraping**: Custom LinkedIn scraper
- **Deployment**: Railway (configured)

### System Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI       │    │   PostgreSQL    │    │   OpenAI API    │
│   Routes        │◄──►│   Database      │    │   LangChain     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Controllers   │    │   Prisma ORM    │    │   RAG System    │
│   Business      │    │   Models        │    │   Embeddings    │
│   Logic         │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Services      │    │   Background    │    │   External      │
│   - Email Gen   │    │   Tasks         │    │   APIs          │
│   - Scraping    │    │   - Ingestion   │    │   - Google      │
│   - Search      │    │   - Processing  │    │   - LinkedIn    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 📋 Prerequisites

Before running this project, ensure you have:

### Required Software
- **Python 3.8+**
- **PostgreSQL 12+**
- **Node.js 16+** (for Prisma)
- **Git**

### Required API Keys
- **OpenAI API Key** (for AI email generation)
- **Google Search API Key** (for lead discovery)
- **SMTP Credentials** (for email sending)

### System Requirements
- **RAM**: Minimum 4GB (8GB recommended)
- **Storage**: 10GB free space
- **Network**: Stable internet connection for API calls

## 🛠️ Installation & Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd lead-generation
```

### 2. Environment Setup

The project includes a comprehensive `.env` file with all necessary environment variables. Update the placeholder values with your actual credentials:

```env
# Database Configuration
DATABASE_URL="postgresql://username:password@localhost:5432/leadgen_db"

# JWT Authentication
JWT_SECRET_KEY="your-super-secret-jwt-key"
JWT_ALGORITHM="HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# OpenAI Configuration
OPENAI_API_KEY="sk-your-openai-api-key"

# Google Search API
GOOGLE_API_KEY="your-google-api-key"
GOOGLE_CSE_ID="your-custom-search-engine-id"

# Email Configuration (SMTP)
SMTP_SERVER="smtp.gmail.com"
SMTP_PORT=587
SMTP_USERNAME="your-email@gmail.com"
SMTP_PASSWORD="your-app-password"

# LinkedIn Configuration (Optional)
LINKEDIN_EMAIL="your-linkedin-email"
LINKEDIN_PASSWORD="your-linkedin-password"

# Application Settings
ENVIRONMENT="development"
DEBUG=True
LOG_LEVEL="INFO"
```

### 3. Database Setup

#### Install PostgreSQL
```bash
# macOS
brew install postgresql
brew services start postgresql

# Ubuntu/Debian
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

#### Create Database
```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE DATABASE leadgen_db;
CREATE USER leadgen_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE leadgen_db TO leadgen_user;
\q
```

### 4. Python Environment Setup

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 5. Database Migration

```bash
# Install Prisma CLI
npm install -g prisma

# Generate Prisma client
prisma generate

# Run database migrations
prisma db push

# (Optional) Seed database with sample data
prisma db seed
```

### 6. Verify Installation

```bash
# Run tests (if available)
pytest

# Check database connection
python -c "from app.services.database import get_db; print('Database connection successful')"
```

## 🚀 Running the Application

### Development Mode

```bash
# Start the FastAPI server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- **Main API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

### Production Mode

```bash
# Install production server
pip install gunicorn

# Run with Gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## 📚 API Usage Examples

### Authentication

```bash
# Login to get JWT token
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password"}'
```

### Search for Leads

```bash
# Search for leads
curl -X POST "http://localhost:8000/search" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "software companies in San Francisco", "limit": 10}'
```

### Generate Personalized Email

```bash
# Generate cold email
curl -X POST "http://localhost:8000/email/generate" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"lead_info": {...}, "template_id": "template_123"}'
```

## 🔧 Configuration

### Key Configuration Files

- `app/config.py`: Application settings
- `prisma/schema.prisma`: Database schema
- `requirements.txt`: Python dependencies
- `railway.json`: Deployment configuration

### Customization Options

1. **Email Templates**: Modify templates in the database
2. **Search Parameters**: Adjust search algorithms in `app/services/search_engine.py`
3. **AI Prompts**: Customize prompts in `app/services/cold_email_template.py`
4. **Scraping Rules**: Modify scraping logic in `app/services/linkedin_scrapper.py`

## 🐛 Troubleshooting

### Common Issues

#### Database Connection Errors
```bash
# Check PostgreSQL status
pg_isready -h localhost -p 5432

# Restart PostgreSQL
brew services restart postgresql  # macOS
sudo systemctl restart postgresql  # Linux
```

#### API Key Issues
- Verify all API keys are correctly set in `.env`
- Check API key permissions and quotas
- Ensure OpenAI account has sufficient credits

#### Import Errors
```bash
# Reinstall dependencies
pip install --force-reinstall -r requirements.txt

# Check Python path
python -c "import sys; print(sys.path)"
```

#### Performance Issues
- Monitor database query performance
- Check API rate limits
- Consider implementing caching for frequent requests

### Logs and Debugging

```bash
# View application logs
tail -f logs/app.log

# Enable debug mode
export DEBUG=True
export LOG_LEVEL=DEBUG
```

## 📈 Monitoring & Maintenance

### Health Checks

```bash
# Check application health
curl http://localhost:8000/health
```

### Database Maintenance

```bash
# Backup database
pg_dump leadgen_db > backup_$(date +%Y%m%d).sql

# Monitor database size
psql -d leadgen_db -c "SELECT pg_size_pretty(pg_database_size('leadgen_db'));"
```

### Performance Monitoring

- Monitor API response times
- Track email delivery rates
- Monitor AI API usage and costs
- Check database query performance

## 🚀 Deployment

### Railway Deployment (Configured)

This project is pre-configured for Railway deployment:

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway up
```

### Docker Deployment (Alternative)

```dockerfile
# Create Dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# Build and run
docker build -t lead-generation .
docker run -p 8000:8000 lead-generation
```

## 🤝 Contributing

### Development Workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/new-feature`
3. Make changes and test thoroughly
4. Commit changes: `git commit -m "Add new feature"`
5. Push to branch: `git push origin feature/new-feature`
6. Create a Pull Request

### Code Standards

- Follow PEP 8 for Python code style
- Add type hints to all functions
- Write comprehensive docstrings
- Include unit tests for new features
- Update documentation as needed

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:

1. Check the troubleshooting section above
2. Review the API documentation at `/docs`
3. Create an issue in the repository
4. Contact the development team

---

**Note**: This platform handles sensitive business data. Ensure proper security measures are in place before deploying to production, including:

- Secure API key management
- Database encryption
- Regular security audits
- Compliance with data protection regulations (GDPR, CCPA, etc.)
- Rate limiting and abuse prevention