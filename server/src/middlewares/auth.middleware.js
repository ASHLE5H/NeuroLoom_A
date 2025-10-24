import jwt from "jsonwebtoken";
import User from "../models/User.js";


export const protectRoute = async (req,res,next)=>{

    try{
        const token = req.cookies.jwt;
        if(!token){
            return res.status(401).json({message:"Unauthorized - No token provided"});
        }
        
        const decoded = jwt.verify(token,process.env.JWT_SECRECT_KEY);  // verifying the token

        if(!decoded){
            return res.status(401).json({message:"Unauthorized - Invalid token"});
        }

        const user = await User.findById(decoded.userId).select("-password")    // extrcating userId from the jwt token and finding user without password 

        if(!user){
            return res.status(401).json({message:"Unauthorized - User not found"});
        }

        req.user = user;

        next();
         
    }catch(error){
        console.log("Error in protecting middleware ", error);
        res.status(500).json({message:"Internal Server Error"});
    }
}