CREATE TABLE IF NOT EXISTS players (
    id UUID PRIMARY KEY,
    first_name VARCHAR(120) NOT NULL,
    last_name VARCHAR(120) NOT NULL,
    birth_date DATE NOT NULL,
    height_cm INTEGER NOT NULL CHECK (height_cm > 0),
    weight_kg INTEGER NOT NULL CHECK (weight_kg > 0),
    primary_position VARCHAR(120) NOT NULL
);
