from ninja import Field, Schema


class LoginIn(Schema):
    # Kullanıcı adı sınırı Django'nunki (150); şifre sınırı uzun girdiyle yük bindirilmesin diye.
    username: str = Field(max_length=150)
    password: str = Field(max_length=1024)


class UserOut(Schema):
    id: int
    username: str
    display_name: str
    initials: str
