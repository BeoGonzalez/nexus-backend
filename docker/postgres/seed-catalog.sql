-- ==============================================================================
-- NEXUS DIGITAL STORE - SEED DATA FOR CATALOG DATABASE
-- Platforms: PS5, PC, Xbox Series, Switch 2
-- ==============================================================================

\connect nexus_catalog;

-- 1. Insertar Plataformas
INSERT INTO platforms (name) VALUES 
    ('PS5'),
    ('PC'),
    ('Xbox Series'),
    ('Switch 2')
ON CONFLICT (name) DO NOTHING;

-- 2. Insertar Géneros
INSERT INTO genres (name) VALUES
    ('Acción'),
    ('Aventura'),
    ('RPG'),
    ('Soulslike'),
    ('FPS'),
    ('Carreras'),
    ('Simulación'),
    ('Estrategia'),
    ('Plataformas'),
    ('Terror'),
    ('Lucha'),
    ('Familiar'),
    ('Ciencia Ficción'),
    ('Mundo Abierto')
ON CONFLICT (name) DO NOTHING;

-- 3. Función auxiliar anónima o bloque DO para insertar juegos y asociar géneros
DO $$
DECLARE
    plat_ps5 uuid;
    plat_pc uuid;
    plat_xbox uuid;
    plat_switch2 uuid;

    g_accion uuid;
    g_aventura uuid;
    g_rpg uuid;
    g_soulslike uuid;
    g_fps uuid;
    g_carreras uuid;
    g_simulacion uuid;
    g_estrategia uuid;
    g_plataformas uuid;
    g_terror uuid;
    g_lucha uuid;
    g_familiar uuid;
    g_scifi uuid;
    g_openworld uuid;

    prod_id uuid;
BEGIN
    -- Obtener IDs de plataformas
    SELECT id INTO plat_ps5 FROM platforms WHERE name = 'PS5';
    SELECT id INTO plat_pc FROM platforms WHERE name = 'PC';
    SELECT id INTO plat_xbox FROM platforms WHERE name = 'Xbox Series';
    SELECT id INTO plat_switch2 FROM platforms WHERE name = 'Switch 2';

    -- Obtener IDs de géneros
    SELECT id INTO g_accion FROM genres WHERE name = 'Acción';
    SELECT id INTO g_aventura FROM genres WHERE name = 'Aventura';
    SELECT id INTO g_rpg FROM genres WHERE name = 'RPG';
    SELECT id INTO g_soulslike FROM genres WHERE name = 'Soulslike';
    SELECT id INTO g_fps FROM genres WHERE name = 'FPS';
    SELECT id INTO g_carreras FROM genres WHERE name = 'Carreras';
    SELECT id INTO g_simulacion FROM genres WHERE name = 'Simulación';
    SELECT id INTO g_estrategia FROM genres WHERE name = 'Estrategia';
    SELECT id INTO g_plataformas FROM genres WHERE name = 'Plataformas';
    SELECT id INTO g_terror FROM genres WHERE name = 'Terror';
    SELECT id INTO g_lucha FROM genres WHERE name = 'Lucha';
    SELECT id INTO g_familiar FROM genres WHERE name = 'Familiar';
    SELECT id INTO g_scifi FROM genres WHERE name = 'Ciencia Ficción';
    SELECT id INTO g_openworld FROM genres WHERE name = 'Mundo Abierto';

    -- =========================================================================
    -- JUEGOS PLAYSTATION 5 (PS5)
    -- =========================================================================

    -- Marvel's Spider-Man 2
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Marvel''s Spider-Man 2',
        'Los Spider-Men Peter Parker y Miles Morales regresan para una nueva aventura en PS5. Balanceate, salta y usa las nuevas alás de telaraña para recorrer la Nueva York de Marvel.',
        49990, 25,
        'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=800&auto=format&fit=crop',
        plat_ps5
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_accion), (prod_id, g_aventura), (prod_id, g_openworld) ON CONFLICT DO NOTHING;

    -- God of War Ragnarök
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'God of War Ragnarök',
        'Embárcate en un viaje épico y conmovedor con Kratos y Atreus mientras luchan por aferrarse y soltarse. Enfrenta a dioses nórdicos a través de los Nueve Reinos.',
        44990, 30,
        'https://images.unsplash.com/photo-1542751371-adc38448a05e?w=800&auto=format&fit=crop',
        plat_ps5
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_accion), (prod_id, g_aventura), (prod_id, g_rpg) ON CONFLICT DO NOTHING;

    -- Demon's Souls Remake
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Demon''s Souls',
        'Completamente reconstruido desde cero y mejorado magistralmente, este remake te invita a experimentar la inquietante historia y el implacable combate del clásico de culto.',
        39990, 15,
        'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=800&auto=format&fit=crop',
        plat_ps5
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_rpg), (prod_id, g_soulslike), (prod_id, g_accion) ON CONFLICT DO NOTHING;

    -- Final Fantasy VII Rebirth
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Final Fantasy VII Rebirth',
        'La aventura desconocida continúa. Cloud y sus amigos escapan de Midgar para adentrarse en el vasto planeta en busca de Sephiroth. Combate en tiempo real dinámico con comando táctico.',
        54990, 20,
        'https://images.unsplash.com/photo-1579373903781-fd5c0c30c4cd?w=800&auto=format&fit=crop',
        plat_ps5
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_rpg), (prod_id, g_accion), (prod_id, g_openworld) ON CONFLICT DO NOTHING;

    -- The Last of Us Part I
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'The Last of Us Part I',
        'Disfruta de la emocionante historia y los inolvidables personajes de Joel y Ellie, reconstruidos con la tecnología del motor gráfico de PS5.',
        42990, 18,
        'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?w=800&auto=format&fit=crop',
        plat_ps5
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_accion), (prod_id, g_aventura), (prod_id, g_terror) ON CONFLICT DO NOTHING;

    -- Gran Turismo 7
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Gran Turismo 7',
        'El simulador de conducción real por excelencia. Compite en más de 400 automóviles y circuitoslegendarios de todo el mundo con respuesta háptica inmersiva.',
        39990, 22,
        'https://images.unsplash.com/photo-1511919884226-fd3cad34687c?w=800&auto=format&fit=crop',
        plat_ps5
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_carreras), (prod_id, g_simulacion) ON CONFLICT DO NOTHING;

    -- =========================================================================
    -- JUEGOS PC GAMING
    -- =========================================================================

    -- Cyberpunk 2077: Ultimate Edition
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Cyberpunk 2077: Ultimate Edition',
        'La experiencia cyberpunk definitiva en PC. Incluye el juego base y la aclamada expansión de suspense y espionaje Phantom Liberty con soporte completo para trazado de rayos y DLSS 3.5.',
        36990, 40,
        'https://images.unsplash.com/photo-1542751371-adc38448a05e?w=800&auto=format&fit=crop',
        plat_pc
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_rpg), (prod_id, g_scifi), (prod_id, g_openworld) ON CONFLICT DO NOTHING;

    -- Baldur's Gate 3
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Baldur''s Gate 3',
        'Reúne a tu grupo y regresa a los Reinos Olvidados en una historia de compañerismo, traición, sacrificio y la atracción del poder absoluto. GOTY 2023 con libertad total de elección.',
        39990, 35,
        'https://images.unsplash.com/photo-1563089145-599997674d42?w=800&auto=format&fit=crop',
        plat_pc
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_rpg), (prod_id, g_estrategia), (prod_id, g_aventura) ON CONFLICT DO NOTHING;

    -- Elden Ring: Shadow of the Erdtree Edition
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Elden Ring: Shadow of the Erdtree Edition',
        'Álzate, Sinluz, y déjate guiar por la gracia para esgrimir el poder del Anillo de Elden. Explora las Tierras Intermedias y la misteriosa Tierra Sombría en una obra maestra sin precedentes.',
        47990, 30,
        'https://images.unsplash.com/photo-1538481199705-c710c4e965fc?w=800&auto=format&fit=crop',
        plat_pc
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_rpg), (prod_id, g_soulslike), (prod_id, g_openworld) ON CONFLICT DO NOTHING;

    -- Black Myth: Wukong
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Black Myth: Wukong',
        'Un juego de rol y acción inspirado en la mitología china. Te pondrás en la piel del Predestinado para explorar un fascinante mundo lleno de maravillas y peligros mientras desentrañas la verdad.',
        39990, 28,
        'https://images.unsplash.com/photo-1511512578047-dfb367046420?w=800&auto=format&fit=crop',
        plat_pc
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_accion), (prod_id, g_rpg) ON CONFLICT DO NOTHING;

    -- Microsoft Flight Simulator 2024
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Microsoft Flight Simulator 2024',
        'Persigue tu sueño en la aviación con una simulación sin igual. Pilota flotas detalladas de aviones comerciales y privados en un planeta Tierra generado en tiempo real con datos satelitales.',
        49990, 20,
        'https://images.unsplash.com/photo-1508614589041-895b88991e3e?w=800&auto=format&fit=crop',
        plat_pc
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_simulacion) ON CONFLICT DO NOTHING;

    -- Counter-Strike 2: Prime Status
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Counter-Strike 2: Prime Status Upgrade',
        'El estándar mundial en shooters tácticos en primera persona. Prime Status te empareja exclusivamente con otros jugadores Prime y desbloquea recompensas semanales e insignias.',
        14990, 100,
        'https://images.unsplash.com/photo-1560253023-3ec5d502959f?w=800&auto=format&fit=crop',
        plat_pc
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_fps), (prod_id, g_accion) ON CONFLICT DO NOTHING;

    -- =========================================================================
    -- JUEGOS XBOX SERIES X|S
    -- =========================================================================

    -- Halo Infinite (Campaña)
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Halo Infinite (Campaña)',
        'Cuando se pierde toda esperanza y el destino de la humanidad pende de un hilo, el Jefe Maestro está listo para enfrentarse al enemigo más despiadado en el anillo Zeta Halo.',
        29990, 25,
        'https://images.unsplash.com/photo-1612287232252-87063f25b293?w=800&auto=format&fit=crop',
        plat_xbox
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_fps), (prod_id, g_scifi), (prod_id, g_accion) ON CONFLICT DO NOTHING;

    -- Forza Horizon 5: Premium Edition
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Forza Horizon 5: Premium Edition',
        'Tu aventura Horizon te espera. Explora los paisajes dinámicos y en constante evolución de México en un mundo abierto con acción ilimitada al volante de cientos de los mejores autos del mundo.',
        46990, 30,
        'https://images.unsplash.com/photo-1552519507-da3b142c6e3d?w=800&auto=format&fit=crop',
        plat_xbox
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_carreras), (prod_id, g_openworld) ON CONFLICT DO NOTHING;

    -- Starfield
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Starfield',
        'El primer universo nuevo en más de 25 años de Bethesda Game Studios. En este juego de rol ambientado entre las estrellas, crea el personaje que desees y explora con una libertad sin igual.',
        34990, 28,
        'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800&auto=format&fit=crop',
        plat_xbox
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_rpg), (prod_id, g_scifi), (prod_id, g_openworld) ON CONFLICT DO NOTHING;

    -- Senua's Saga: Hellblade II
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Senua''s Saga: Hellblade II',
        'La secuela de la aclamada obra Hellblade. Senua regresa en un viaje brutal de supervivencia a través de los mitos y el tormento de la Islandia vikinga con fidelidad visual de vanguardia en Unreal Engine 5.',
        38990, 18,
        'https://images.unsplash.com/photo-1534447677768-be436bb09401?w=800&auto=format&fit=crop',
        plat_xbox
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_aventura), (prod_id, g_terror), (prod_id, g_accion) ON CONFLICT DO NOTHING;

    -- Gears 5: Game of the Year Edition
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Gears 5: Game of the Year Edition',
        'Con la guerra total acercándose, Kait Diaz se separa para descubrir su conexión con el enemigo y descubre el verdadero peligro para Sera: ella misma. Incluye la expansión Hivebusters.',
        19990, 22,
        'https://images.unsplash.com/photo-1579373903781-fd5c0c30c4cd?w=800&auto=format&fit=crop',
        plat_xbox
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_accion), (prod_id, g_fps) ON CONFLICT DO NOTHING;

    -- =========================================================================
    -- JUEGOS NINTENDO SWITCH 2
    -- =========================================================================

    -- Mario Kart X (Switch 2 Edition)
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Mario Kart X (Switch 2 Edition)',
        'La nueva era de las carreras de karts en Switch 2. Pistas interdimensionales, resolución 4K reescalada en dock y física avanzada con modo multijugador local y online para hasta 16 jugadores.',
        59990, 50,
        'https://images.unsplash.com/photo-1566576912321-d58ddd743fb5?w=800&auto=format&fit=crop',
        plat_switch2
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_carreras), (prod_id, g_familiar) ON CONFLICT DO NOTHING;

    -- The Legend of Zelda: Tears of the Kingdom (Next-Gen Enhanced)
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'The Legend of Zelda: Tears of the Kingdom (Enhanced Edition)',
        'Explora los vastos cielos, la superficie y las profundidades de Hyrule con tasa de refresco a 60 FPS estables y texturas ultra detalladas optimizadas para la arquitectura de Switch 2.',
        54990, 40,
        'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=800&auto=format&fit=crop',
        plat_switch2
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_aventura), (prod_id, g_openworld), (prod_id, g_rpg) ON CONFLICT DO NOTHING;

    -- Super Mario Odyssey 2
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Super Mario Odyssey 2',
        'Mario y Cappy vuelven a embarcarse en un viaje global en la Odyssey para descubrir nuevos reinos inexplorados, capturar nuevas criaturas con habilidades inéditas y rescatar el Reino Champiñón.',
        59990, 45,
        'https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=800&auto=format&fit=crop',
        plat_switch2
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_plataformas), (prod_id, g_familiar), (prod_id, g_aventura) ON CONFLICT DO NOTHING;

    -- Metroid Prime 4: Beyond
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Metroid Prime 4: Beyond',
        'La legendaria cazarrecompensas Samus Aran regresa para una nueva misión galáctica en primera persona. Iluminación volumétrica, entornos alienígenas hostiles y acción FPS de alta precisión.',
        56990, 30,
        'https://images.unsplash.com/photo-1579373903781-fd5c0c30c4cd?w=800&auto=format&fit=crop',
        plat_switch2
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_accion), (prod_id, g_scifi), (prod_id, g_fps) ON CONFLICT DO NOTHING;

    -- Pokémon Legends: Z-A (Switch 2 Edition)
    INSERT INTO products (title, description, price_clp, stock, image_url, platform_id)
    VALUES (
        'Pokémon Legends: Z-A (Switch 2 Edition)',
        'Una nueva y ambiciosa aventura ambientada en Ciudad Luminalia, donde un plan de desarrollo urbanístico promete convertir la urbe en un lugar donde personas y Pokémon conviven en armonía.',
        54990, 35,
        'https://images.unsplash.com/photo-1613771404784-3a5686aa2be3?w=800&auto=format&fit=crop',
        plat_switch2
    ) RETURNING id INTO prod_id;
    INSERT INTO product_genres (product_id, genre_id) VALUES (prod_id, g_rpg), (prod_id, g_aventura) ON CONFLICT DO NOTHING;

END $$;

