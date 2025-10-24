import jwt from 'jsonwebtoken';
import User from '../models/User.js';

export async function signup(req,res){
    const {email,password,fullName} = req.body;

    try{
        if(!email || !password || !fullName){
            return res.status(400).json({message:"All fields are required"});
        }
        const passwordRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/;

        if (!passwordRegex.test(password)) {
           return res.status(400).json({
            message:
            "Password must be at least 8 characters long, include 1 uppercase letter, 1 lowercase letter, 1 number, and 1 special character.",
            });
        }

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

        if (!emailRegex.test(email)) {
            return res.status(400).json({ message: "Invalid email format" });
        }

        const existingUser = await User.findOne({email})
        if(existingUser){
            return res.status(400).json({message:"Email already exists. Please use different one"});
        }


        const newUser = await User.create({
        email,
        fullName,
        password,
        })

        const token = jwt.sign({userId:newUser._id} , process.env.JWT_SECRECT_KEY , {expiresIn:"7d"}); 
        res.cookie("jwt",token , {
            maxAge: 7 * 24 * 60 * 60 * 1000,  //7days
            httpOnly :true,
            sameSite : "strict",
            secure : process.env.NODE_ENV === "production"
        });

        res.status(201).json({success:true , user:newUser});
    }
    catch(error){
        console.log("Error in sign controller", error);
        res.status(500).json({message:"Interval Server Error"});
    }
}



export async function login(req,res){
    try{
        const {email,password} = req.body;

        if(!email || !password){
            return res.status(400).json({message:"All fields are required"});
        }

        const user = await User.findOne({email});
        if(!user) return res.status(404).json({message:"Invalid email or password"});

        const isPasswordCorrect = await user.matchPassword(password);
        if(!isPasswordCorrect) return res.status(401).json({message:"Invalid email or password"})

        const token = jwt.sign({userId:user._id} , process.env.JWT_SECRECT_KEY , {expiresIn:"7d"});
        res.cookie("jwt",token , {
        maxAge: 7 * 24 * 60 * 60 * 1000,  //7days
        httpOnly :true,
        sameSite : "strict",
        secure : process.env.NODE_ENV === "production"
    });

    res.status(200).json({success:true , user})

    }catch(error){
        console.log("Error in login controller ", error.message);
        res.status(500).json({message:"Internal server error"});
    }
}