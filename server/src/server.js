import express from 'express';
import dotenv from 'dotenv';
import authRoutes from './routes/auth.route.js'
import chatRoutes from './routes/auth.route.js'
import { connectDB } from './lib/db.js';
import cors from 'cors';
import cookieParser from "cookie-parser";

const app = express();

dotenv.config();

const PORT = process.env.PORT;

app.use(cors({
    origin:"http://localhost:5173",
    credentials:true
}))

app.use(express.json());
app.use(cookieParser());



app.use("/auth",authRoutes);
app.use("/chat",chatRoutes)


app.listen(PORT,()=>{
    console.log(`Server is running on port http://localhost:${PORT}`);
    connectDB();
})