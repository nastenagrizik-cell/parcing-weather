from pydantic import BaseModel, HttpUrl

class CityCreate(BaseModel):
    name: str
    rp5_url: HttpUrl
    sheet_name: str
    is_active: bool = True
